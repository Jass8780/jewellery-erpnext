# Copyright (c) 2023, Nirali and contributors
# For license information, please see license.txt
"""
Background job processors for Department IR and Main Slip.
Hooked via doc_events so heavy logic runs in background; on_submit only enqueues.
- Batch size 20 for operations/loss_details
- Commit after each batch; rollback and log_error on exception per batch
- BOM/Item reads cached within each job run
"""
import frappe
from frappe import _
from frappe.utils import flt

# Per-job cache for BOM and Item (cleared at start of each process_*)
_bom_cache = {}
_item_cache = {}

# Batch size for Department IR operations and Main Slip loss_details
BATCH_SIZE = 20
DEPARTMENT_IR_JOB_TIMEOUT = 14400  # 4 hours
MAIN_SLIP_JOB_TIMEOUT = 3600       # 1 hour


def _clear_caches():
	global _bom_cache, _item_cache
	_bom_cache = {}
	_item_cache = {}


def _get_bom_cached(name):
	if name not in _bom_cache:
		try:
			_bom_cache[name] = frappe.get_cached_doc("BOM", name)
		except Exception:
			_bom_cache[name] = None
	return _bom_cache[name]


def _get_item_cached(name):
	if name not in _item_cache:
		try:
			_item_cache[name] = frappe.get_cached_doc("Item", name)
		except Exception:
			_item_cache[name] = None
	return _item_cache[name]


def _filter_se_items(add_to_transit, start_transit):
	"""Skip zero-quantity and SNC crate SLEs. Returns filtered lists."""
	def valid(row):
		if flt(row.get("qty"), 3) <= 0:
			return False
		item_code = row.get("item_code") or ""
		# Skip SNC crate items (common pattern: item_code or item_group)
		if "SNC" in (item_code or "").upper():
			return False
		try:
			item = _get_item_cached(item_code)
			if item and getattr(item, "item_group", None) and "SNC" in (item.item_group or "").upper():
				return False
		except Exception:
			pass
		return True

	return [r for r in (add_to_transit or []) if valid(r)], [r for r in (start_transit or []) if valid(r)]


# --- Department IR ---

def enqueue_department_ir(doc, method=None):
	"""Enqueue Department IR processing. Called from doc_events on_submit. No heavy logic here."""
	if not doc or getattr(doc, "docstatus", 0) != 1:
		return
	docname = doc.name if hasattr(doc, "name") else doc
	frappe.enqueue(
		method="jewellery_erpnext.jobs.process_department_ir",
		queue="long",
		timeout=DEPARTMENT_IR_JOB_TIMEOUT,
		is_async=True,
		docname=docname,
	)


def process_department_ir(docname):
	"""
	Process Department IR in background: sort operations by operation, item_code;
	batch of 20; create Stock Entries, update MOP balance; skip zero-qty/SNC SLEs; commit per batch.
	"""
	_clear_caches()
	try:
		doc = frappe.get_doc("Department IR", docname)
	except Exception as e:
		frappe.log_error(title=f"Department IR {docname} load failed", message=frappe.get_traceback())
		raise

	operations = list(doc.department_ir_operation or [])
	if not operations:
		_update_ir_status(docname, "Completed", 100)
		frappe.db.commit()
		return

	# Sort by operation, then item_code (operation from Manufacturing Operation)
	mop_names = list(set(r.manufacturing_operation for r in operations))
	mop_operation_map = {}
	if mop_names:
		for mop in frappe.db.get_all(
			"Manufacturing Operation",
			filters={"name": ["in", mop_names]},
			fields=["name", "operation"],
		):
			mop_operation_map[mop.name] = mop.operation or ""

	def sort_key(row):
		op = mop_operation_map.get(row.manufacturing_operation) or ""
		item = getattr(row, "item_code", None) or row.get("item_code") or ""
		return (op, item, row.manufacturing_operation or "")

	sorted_ops = sorted(operations, key=sort_key)

	# Prepare warehouse data once
	from jewellery_erpnext.jewellery_erpnext.doctype.department_ir.department_ir import (
		_process_issue_batch,
		_process_receive_batch,
		_prepare_warehouse_data,
		update_mop_balances_bulk,
	)
	warehouse_data = _prepare_warehouse_data(doc)

	processed = 0
	total = len(sorted_ops)
	for i in range(0, total, BATCH_SIZE):
		batch = sorted_ops[i : i + BATCH_SIZE]
		try:
			if doc.type == "Issue":
				_process_issue_batch(doc, batch, warehouse_data)
			else:
				_process_receive_batch(doc, batch, warehouse_data)
			# Update MOP balances for this batch
			update_mop_balances_bulk(doc, batch)
			processed += len(batch)
			_update_ir_status(docname, "Processing", int((processed / total) * 100))
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			frappe.log_error(
				title=f"Department IR {docname} batch failed (ops {i}-{i+len(batch)})",
				message=frappe.get_traceback(),
			)
			_update_ir_status(docname, "Failed", None, error_log=frappe.get_traceback())
			frappe.db.commit()
			raise

	_update_ir_status(docname, "Completed", 100)
	frappe.db.commit()


def _update_ir_status(ir_name, status, progress=None, error_log=None):
	try:
		updates = {"processing_status": status}
		if progress is not None:
			updates["progress_percentage"] = progress
		if error_log:
			updates["error_log"] = error_log
		frappe.db.set_value("Department IR", ir_name, updates)
	except Exception:
		pass


# --- Main Slip ---

def enqueue_main_slip(doc, method=None):
	"""Enqueue Main Slip submit processing. Called from doc_events on_submit. No heavy logic here."""
	if not doc or getattr(doc, "docstatus", 0) != 1:
		return
	docname = doc.name if hasattr(doc, "name") else doc
	frappe.enqueue(
		method="jewellery_erpnext.jobs.process_main_slip",
		queue="long",
		timeout=MAIN_SLIP_JOB_TIMEOUT,
		is_async=True,
		docname=docname,
	)


def process_main_slip(docname):
	"""
	Process Main Slip submit in background: create_loss_stock_entries in batches of 20;
	commit per batch; use BOM/Item cache; log_error and rollback on exception per batch.
	"""
	_clear_caches()
	try:
		doc = frappe.get_doc("Main Slip", docname)
	except Exception as e:
		frappe.log_error(title=f"Main Slip {docname} load failed", message=frappe.get_traceback())
		raise

	loss_details = list(doc.loss_details or [])
	if not loss_details:
		frappe.db.commit()
		return

	from jewellery_erpnext.jewellery_erpnext.doctype.main_slip.main_slip import create_loss_stock_entries

	frappe.db.MAX_WRITES_PER_TRANSACTION = (frappe.db.MAX_WRITES_PER_TRANSACTION or 1000) * 16

	for i in range(0, len(loss_details), BATCH_SIZE):
		batch = loss_details[i : i + BATCH_SIZE]
		try:
			for row in batch:
				create_loss_stock_entries(
					doc,
					row.item_code,
					row.variant_of,
					row.received_qty,
					flt(row.msl_qty, 3) - flt(row.received_qty, 3),
				)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			frappe.log_error(
				title=f"Main Slip {docname} batch failed (rows {i}-{i+len(batch)})",
				message=frappe.get_traceback(),
			)
			raise
