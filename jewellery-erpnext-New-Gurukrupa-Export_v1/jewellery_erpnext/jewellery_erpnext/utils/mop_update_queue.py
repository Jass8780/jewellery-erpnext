"""
Deferred MOP Update Queue System

This module implements a deferred, batched, and aggregated MOP update system
to reduce database locking and improve performance under high concurrency.

Key Features:
- Collects MOP deltas during IR/Stock Entry processing (no immediate DB writes)
- Aggregates deltas by MOP+Item+Warehouse before writing
- Processes updates in background jobs (batched, SQL-based)
- Serializes per-MOP to prevent deadlocks
- Only updates rows where delta != 0
"""

import frappe
from frappe import _
from frappe.utils import now, cint, flt
from collections import defaultdict
import json
import hashlib


# ============================================================================
# DELTA COLLECTION (During IR/Stock Entry Processing)
# ============================================================================

def queue_mop_table_insert(mop_name, table_type, row_data, source_doc=None):
	"""
	Queue a MOP table row insert instead of inserting immediately.
	
	Args:
		mop_name: Manufacturing Operation name
		table_type: One of: "department_source", "department_target", 
		            "employee_source", "employee_target"
		row_data: Dict with row data (item_code, qty, batch_no, etc.)
		source_doc: Source document (Stock Entry, Department IR, Employee IR)
	
	This function collects deltas in memory/cache and does NOT write to DB.
	"""
	if not mop_name or not table_type or not row_data:
		return
	
	# Normalize table type
	table_type = table_type.lower().replace(" ", "_")
	
	# Create delta key for aggregation
	delta_key = _create_delta_key(mop_name, table_type, row_data)
	
	# Store delta in cache (will be persisted to queue table by background job)
	cache_key = f"mop_delta:{delta_key}"
	
	# Get existing delta or create new
	existing = frappe.cache().get(cache_key)
	if existing:
		delta = json.loads(existing)
		# Aggregate: Add quantities
		delta["qty"] = flt(delta.get("qty", 0)) + flt(row_data.get("qty", 0))
		delta["pcs"] = flt(delta.get("pcs", 0)) + flt(row_data.get("pcs", 0))
		delta["gross_weight"] = flt(delta.get("gross_weight", 0)) + flt(row_data.get("gross_weight", 0))
		delta["count"] = delta.get("count", 0) + 1
	else:
		delta = {
			"mop": mop_name,
			"table_type": table_type,
			"item_code": row_data.get("item_code"),
			"batch_no": row_data.get("batch_no"),
			"serial_no": row_data.get("serial_no"),
			"qty": flt(row_data.get("qty", 0)),
			"pcs": flt(row_data.get("pcs", 0)),
			"gross_weight": flt(row_data.get("gross_weight", 0)),
			"warehouse": row_data.get("s_warehouse") or row_data.get("t_warehouse"),
			"inventory_type": row_data.get("inventory_type"),
			"customer": row_data.get("customer"),
			"is_customer_item": row_data.get("is_customer_item"),
			"sub_setting_type": row_data.get("sub_setting_type"),
			"sed_item": row_data.get("name"),  # Stock Entry Detail name
			"source_doc": source_doc.name if source_doc else None,
			"source_doctype": source_doc.doctype if source_doc else None,
			"count": 1,
			"timestamp": now()
		}
	
	# Store in cache (expires in 1 hour - should be processed much sooner)
	frappe.cache().set_value(cache_key, json.dumps(delta, default=str), expires_in_sec=3600)
	
	# Also add to queue list for batch processing
	queue_list_key = "mop_update_queue:list"
	queue_list = frappe.cache().get_value(queue_list_key) or set()
	queue_list.add(delta_key)
	frappe.cache().set_value(queue_list_key, queue_list, expires_in_sec=3600)


def queue_mop_balance_recompute(mop_name, source_doc=None):
	"""
	Queue a MOP balance table recomputation.
	
	Instead of calling set_mop_balance_table() immediately, queue it for
	batch processing in background.
	"""
	if not mop_name:
		return
	
	# Add to recompute queue
	recompute_key = f"mop_recompute:{mop_name}"
	frappe.cache().set_value(recompute_key, json.dumps({
		"mop": mop_name,
		"source_doc": source_doc.name if source_doc else None,
		"source_doctype": source_doc.doctype if source_doc else None,
		"timestamp": now()
	}, default=str), expires_in_sec=3600)
	
	# Add to queue list
	queue_list_key = "mop_recompute_queue:list"
	recompute_list = frappe.cache().get_value(queue_list_key) or set()
	recompute_list.add(mop_name)
	frappe.cache().set_value(queue_list_key, recompute_list, expires_in_sec=3600)


def _create_delta_key(mop_name, table_type, row_data):
	"""Create a unique key for delta aggregation"""
	# Aggregate by: mop + table_type + item + batch + warehouse
	key_parts = [
		mop_name,
		table_type,
		row_data.get("item_code", ""),
		row_data.get("batch_no", ""),
		row_data.get("s_warehouse") or row_data.get("t_warehouse", ""),
		row_data.get("inventory_type", ""),
		row_data.get("customer", ""),
	]
	key_str = "|".join(str(p) for p in key_parts)
	return hashlib.md5(key_str.encode()).hexdigest()


# ============================================================================
# BACKGROUND JOB: Process MOP Updates
# ============================================================================

@frappe.whitelist()
def process_mop_updates_async(batch_size=100):
	"""
	Background job to process queued MOP updates in batches.
	
	This function:
	1. Collects all queued deltas from cache
	2. Aggregates deltas by MOP+Item+Batch+Warehouse
	3. Applies updates using SQL (not ORM)
	4. Recomputes MOP balances after batch
	5. Commits once per batch
	
	Args:
		batch_size: Number of MOPs to process per batch
	"""
	try:
		# Get all queued delta keys
		queue_list_key = "mop_update_queue:list"
		delta_keys_set = frappe.cache().get_value(queue_list_key) or set()
		delta_keys = list(delta_keys_set) if delta_keys_set else []
		
		if not delta_keys:
			return {"status": "success", "message": "No MOP updates queued"}
		
		# Collect all deltas
		all_deltas = {}
		for delta_key in delta_keys:
			cache_key = f"mop_delta:{delta_key}"
			delta_json = frappe.cache().get(cache_key)
			if delta_json:
				delta = json.loads(delta_json)
				# Use (mop, table_type, item, batch, warehouse) as aggregation key
				agg_key = (
					delta["mop"],
					delta["table_type"],
					delta["item_code"],
					delta.get("batch_no", ""),
					delta.get("warehouse", ""),
					delta.get("inventory_type", ""),
					delta.get("customer", "")
				)
				if agg_key not in all_deltas:
					all_deltas[agg_key] = delta.copy()
				else:
					# Aggregate quantities
					existing = all_deltas[agg_key]
					existing["qty"] = flt(existing["qty"]) + flt(delta["qty"])
					existing["pcs"] = flt(existing["pcs"]) + flt(delta["pcs"])
					existing["gross_weight"] = flt(existing["gross_weight"]) + flt(delta["gross_weight"])
					existing["count"] = existing.get("count", 0) + delta.get("count", 1)
		
		if not all_deltas:
			# Clear queue if no valid deltas
			frappe.cache().delete(queue_list_key)
			return {"status": "success", "message": "No valid deltas found"}
		
		# Group by MOP for serialized processing
		mop_groups = defaultdict(list)
		for agg_key, delta in all_deltas.items():
			mop_name = agg_key[0]
			mop_groups[mop_name].append((agg_key, delta))
		
		# Process MOPs in batches
		mop_list = list(mop_groups.keys())
		processed = 0
		errors = []
		
		for i in range(0, len(mop_list), batch_size):
			mop_batch = mop_list[i:i+batch_size]
			
			for mop_name in mop_batch:
				# Serialize per-MOP to prevent deadlocks
				lock_key = f"mop_lock:{mop_name}"
				if not frappe.cache().get_value(lock_key):
					try:
						# Acquire lock (expires in 5 minutes)
						frappe.cache().set_value(lock_key, "locked", expires_in_sec=300)
						
						# Process all deltas for this MOP
						mop_deltas = mop_groups[mop_name]
						_apply_mop_deltas(mop_name, mop_deltas)
						
						processed += 1
					except Exception as e:
						errors.append(f"MOP {mop_name}: {str(e)}")
						frappe.log_error(f"Error processing MOP {mop_name}: {str(e)}")
					finally:
						# Release lock
						frappe.cache().delete_value(lock_key)
				else:
					# MOP is locked, skip for now (will be retried)
					pass
			
			# Commit after each batch
			frappe.db.commit()
		
		# Clear processed deltas from cache
		for delta_key in delta_keys:
			frappe.cache().delete_value(f"mop_delta:{delta_key}")
		frappe.cache().delete_value(queue_list_key)
		
		# Process recompute queue
		_process_mop_recompute_queue(batch_size)
		
		return {
			"status": "success",
			"processed": processed,
			"errors": errors if errors else None
		}
		
	except Exception as e:
		frappe.log_error(f"Error in process_mop_updates_async: {str(e)}")
		raise


def _apply_mop_deltas(mop_name, mop_deltas):
	"""
	Apply aggregated deltas to MOP tables using SQL updates.
	
	This function:
	- Inserts/updates MOP child table rows using SQL
	- Only writes rows where delta != 0
	- Uses bulk SQL operations (not ORM)
	"""
	from frappe.utils import now
	
	# Group deltas by table type
	table_groups = defaultdict(list)
	for agg_key, delta in mop_deltas:
		table_type = delta["table_type"]
		table_groups[table_type].append(delta)
	
	# Map table types to doctype names
	table_doctype_map = {
		"department_source_table": "Department Source Table",
		"department_target_table": "Department Target Table",
		"employee_source_table": "Employee Source Table",
		"employee_target_table": "Employee Target Table"
	}
	
	# Process each table type
	for table_type, deltas in table_groups.items():
		doctype_name = table_doctype_map.get(table_type)
		if not doctype_name:
			continue
		
		# Prepare bulk insert data
		rows_to_insert = []
		for delta in deltas:
			# Skip zero deltas
			if flt(delta.get("qty", 0)) == 0 and flt(delta.get("pcs", 0)) == 0:
				continue
			
			row_data = {
				"name": frappe.generate_hash(length=10),
				"parent": mop_name,
				"parenttype": "Manufacturing Operation",
				"parentfield": table_type,
				"creation": now(),
				"modified": now(),
				"item_code": delta.get("item_code"),
				"batch_no": delta.get("batch_no"),
				"serial_no": delta.get("serial_no"),
				"qty": delta.get("qty", 0),
				"pcs": delta.get("pcs", 0),
				"gross_weight": delta.get("gross_weight", 0),
				"warehouse": delta.get("warehouse"),
				"inventory_type": delta.get("inventory_type"),
				"customer": delta.get("customer"),
				"is_customer_item": delta.get("is_customer_item"),
				"sub_setting_type": delta.get("sub_setting_type"),
				"sed_item": delta.get("sed_item"),
			}
			rows_to_insert.append(row_data)
		
		# Bulk insert using SQL
		if rows_to_insert:
			try:
				frappe.db.bulk_insert(doctype_name, rows_to_insert, chunk_size=500)
			except Exception as e:
				frappe.log_error(f"Bulk insert failed for {doctype_name}, MOP {mop_name}: {str(e)}")
				raise


def _process_mop_recompute_queue(batch_size=50):
	"""
	Process queued MOP balance recomputations.
	
	Recomputes MOP Balance Table from source/target tables using SQL.
	"""
	recompute_list_key = "mop_recompute_queue:list"
	mop_names_set = frappe.cache().get_value(recompute_list_key) or set()
	mop_names = list(mop_names_set) if mop_names_set else []
	
	if not mop_names:
		return
	
	# Process in batches
	for i in range(0, len(mop_names), batch_size):
		mop_batch = list(mop_names)[i:i+batch_size]
		
		for mop_name in mop_batch:
			try:
				# Recompute balance using SQL (not ORM)
				_recompute_mop_balance_sql(mop_name)
			except Exception as e:
				frappe.log_error(f"Error recomputing MOP balance for {mop_name}: {str(e)}")
		
		frappe.db.commit()
	
	# Clear queue
	frappe.cache().delete_value(recompute_list_key)


def _recompute_mop_balance_sql(mop_name):
	"""
	Recompute MOP Balance Table using SQL aggregation.
	
	This replaces the ORM-based set_mop_balance_table() with SQL for performance.
	"""
	# Get all source/target table data
	source_data = frappe.db.sql("""
		SELECT 
			item_code, batch_no, serial_no,
			SUM(qty) as qty, SUM(pcs) as pcs, SUM(gross_weight) as gross_weight,
			warehouse, inventory_type, customer, is_customer_item, sub_setting_type
		FROM `tabDepartment Source Table`
		WHERE parent = %s
		GROUP BY item_code, batch_no, serial_no, warehouse, inventory_type, customer, is_customer_item, sub_setting_type
		
		UNION ALL
		
		SELECT 
			item_code, batch_no, serial_no,
			SUM(qty) as qty, SUM(pcs) as pcs, SUM(gross_weight) as gross_weight,
			warehouse, inventory_type, customer, is_customer_item, sub_setting_type
		FROM `tabEmployee Source Table`
		WHERE parent = %s
		GROUP BY item_code, batch_no, serial_no, warehouse, inventory_type, customer, is_customer_item, sub_setting_type
	""", (mop_name, mop_name), as_dict=True)
	
	target_data = frappe.db.sql("""
		SELECT 
			item_code, batch_no, serial_no,
			SUM(qty) as qty, SUM(pcs) as pcs, SUM(gross_weight) as gross_weight,
			warehouse, inventory_type, customer, is_customer_item, sub_setting_type
		FROM `tabDepartment Target Table`
		WHERE parent = %s
		GROUP BY item_code, batch_no, serial_no, warehouse, inventory_type, customer, is_customer_item, sub_setting_type
		
		UNION ALL
		
		SELECT 
			item_code, batch_no, serial_no,
			SUM(qty) as qty, SUM(pcs) as pcs, SUM(gross_weight) as gross_weight,
			warehouse, inventory_type, customer, is_customer_item, sub_setting_type
		FROM `tabEmployee Target Table`
		WHERE parent = %s
		GROUP BY item_code, batch_no, serial_no, warehouse, inventory_type, customer, is_customer_item, sub_setting_type
	""", (mop_name, mop_name), as_dict=True)
	
	# Aggregate: source - target = balance
	balance_map = {}
	
	# Add sources
	for row in source_data:
		key = (
			row.item_code, row.batch_no or "", row.serial_no or "",
			row.warehouse or "", row.inventory_type or "", row.customer or "",
			row.is_customer_item or 0, row.sub_setting_type or ""
		)
		if key not in balance_map:
			balance_map[key] = {
				"qty": 0, "pcs": 0, "gross_weight": 0,
				"item_code": row.item_code,
				"batch_no": row.batch_no,
				"serial_no": row.serial_no,
				"warehouse": row.warehouse,
				"inventory_type": row.inventory_type,
				"customer": row.customer,
				"is_customer_item": row.is_customer_item,
				"sub_setting_type": row.sub_setting_type,
			}
		balance_map[key]["qty"] += flt(row.qty)
		balance_map[key]["pcs"] += flt(row.pcs)
		balance_map[key]["gross_weight"] += flt(row.gross_weight)
	
	# Subtract targets
	for row in target_data:
		key = (
			row.item_code, row.batch_no or "", row.serial_no or "",
			row.warehouse or "", row.inventory_type or "", row.customer or "",
			row.is_customer_item or 0, row.sub_setting_type or ""
		)
		if key not in balance_map:
			balance_map[key] = {
				"qty": 0, "pcs": 0, "gross_weight": 0,
				"item_code": row.item_code,
				"batch_no": row.batch_no,
				"serial_no": row.serial_no,
				"warehouse": row.warehouse,
				"inventory_type": row.inventory_type,
				"customer": row.customer,
				"is_customer_item": row.is_customer_item,
				"sub_setting_type": row.sub_setting_type,
			}
		balance_map[key]["qty"] -= flt(row.qty)
		balance_map[key]["pcs"] -= flt(row.pcs)
		balance_map[key]["gross_weight"] -= flt(row.gross_weight)
	
	# Delete existing balance rows
	frappe.db.sql("DELETE FROM `tabMOP Balance Table` WHERE parent = %s", (mop_name,))
	
	# Insert new balance rows (only where qty != 0)
	from frappe.utils import now
	rows_to_insert = []
	for key, balance in balance_map.items():
		if flt(balance["qty"]) != 0 or flt(balance["pcs"]) != 0:
			rows_to_insert.append({
				"name": frappe.generate_hash(length=10),
				"parent": mop_name,
				"parenttype": "Manufacturing Operation",
				"parentfield": "mop_balance_table",
				"creation": now(),
				"modified": now(),
				"item_code": balance["item_code"],
				"batch_no": balance["batch_no"],
				"serial_no": balance["serial_no"],
				"qty": balance["qty"],
				"pcs": balance["pcs"],
				"gross_weight": balance["gross_weight"],
				"warehouse": balance["warehouse"],
				"inventory_type": balance["inventory_type"],
				"customer": balance["customer"],
				"is_customer_item": balance["is_customer_item"],
				"sub_setting_type": balance["sub_setting_type"],
			})
	
	if rows_to_insert:
		frappe.db.bulk_insert("MOP Balance Table", rows_to_insert, chunk_size=500)


# ============================================================================
# ENQUEUE BACKGROUND JOB
# ============================================================================

def enqueue_mop_updates_processing():
	"""
	Enqueue background job to process MOP updates.
	
	Call this after collecting deltas (e.g., after Stock Entry submit,
	after IR processing).
	"""
	frappe.enqueue(
		method="jewellery_erpnext.jewellery_erpnext.utils.mop_update_queue.process_mop_updates_async",
		queue="long",
		timeout=7200,  # 2 hours
		is_async=True,
		job_name="process_mop_updates",
		batch_size=100
	)

