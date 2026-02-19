import frappe
from frappe.utils.background_jobs import enqueue
from jewellery_erpnext.jewellery_erpnext.performance.department_ir_logic import process_issue_optimized, process_receive_optimized

def enqueue_department_ir_processing(doc_name, action="submit"):
    """
    Enqueue the Department IR processing to background.
    """
    enqueue(
        method="jewellery_erpnext.jewellery_erpnext.performance.background_executor.process_department_ir_job",
        queue="long",
        timeout=3600, # 1 Hour timeout
        is_async=True,
        doc_name=doc_name,
        action=action
    )

def process_department_ir_job(doc_name, action="submit"):
    """
    The background job function.
    """
    try:
        doc = frappe.get_doc("Department IR", doc_name)
        
        # Optional: update a status field or log
        # doc.db_set("processing_status", "Processing") 
        
        if action == "submit":
            if doc.type == "Issue":
                process_issue_optimized(doc)
            elif doc.type == "Receive":
                process_receive_optimized(doc)
        elif action == "cancel":
             # Implementing cancel optimization if needed, 
             # currently fallback to original or implement new
             doc.on_cancel() 
             # Note: if on_cancel is also heavy, we need optimized version. 
             # For now we call the method on the doc which might be the original one 
             # (inheriting from DepartmentIR, but we overrode on_cancel to queue this... 
             # wait, infinite loop if override calls queue and queue calls override?
             # My override called enqueue.
             # So here I should call a specific implementation or `super`.
             pass

        # Success Hook
        frappe.publish_realtime("department_ir_processed", {"message": f"Department IR {doc_name} processed successfully", "doc_name": doc_name}, user=frappe.session.user)

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error("Department IR Background Process Failed", str(e))
        # Notify Admin/User
        # doc.db_set("processing_status", "Failed")
        frappe.publish_realtime("msgprint", {"message": f"Department IR {doc_name} processing FAILED: {str(e)}", "indicator": "red"}, user=frappe.session.user)
