import frappe
from frappe import _
from jewellery_erpnext.jewellery_erpnext.doctype.department_ir.department_ir import DepartmentIR


class PerformanceDepartmentIR(DepartmentIR):
	def on_submit(self):
		"""
		Overridden on_submit to bypass synchronous heavy logic.
		Enqueue is done via doc_events -> jewellery_erpnext.jobs.enqueue_department_ir
		"""
		self.add_comment("Info", "Submit initiated. Processing in background...")
		frappe.msgprint(
			_("Department IR {0} has been queued for processing. Refresh later to check status.").format(self.name)
		)

	def on_cancel(self):
		# Cancel still runs synchronously (original logic)
		super().on_cancel()
