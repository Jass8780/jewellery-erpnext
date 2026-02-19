# Copyright (c) 2023, Nirali and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""
	Add indexes to optimize Department IR queries
	"""
	indexes = [
		{
			"doctype": "Stock Entry Detail",
			"columns": ["manufacturing_operation", "docstatus", "t_warehouse"],
			"index_name": "idx_mop_docstatus_twh"
		},
		{
			"doctype": "Stock Entry Detail",
			"columns": ["manufacturing_work_order", "docstatus", "department"],
			"index_name": "idx_mwo_docstatus_dept"
		},
		{
			"doctype": "MOP Balance Table",
			"columns": ["parent", "item_code", "batch_no"],
			"index_name": "idx_parent_item_batch"
		},
		{
			"doctype": "Manufacturing Operation",
			"columns": ["department_ir_status", "status", "department"],
			"index_name": "idx_dir_status_dept"
		},
		{
			"doctype": "Stock Entry",
			"columns": ["department_ir", "docstatus", "auto_created"],
			"index_name": "idx_dir_docstatus_auto"
		},
		{
			"doctype": "Stock Entry Detail",
			"columns": ["parent", "manufacturing_operation"],
			"index_name": "idx_parent_mop"
		},
		{
			"doctype": "Manufacturing Operation",
			"columns": ["department_issue_id", "manufacturing_work_order"],
			"index_name": "idx_dir_issue_mwo"
		}
	]
	
	for index_info in indexes:
		doctype = index_info["doctype"]
		columns = index_info["columns"]
		index_name = index_info["index_name"]
		
		try:
			# Check if index already exists
			existing_indexes = frappe.db.sql("""
				SHOW INDEX FROM `tab{doctype}` 
				WHERE Key_name = %s
			""".format(doctype=doctype), (index_name,), as_dict=True)
			
			if existing_indexes:
				frappe.log_error(f"Index {index_name} already exists on {doctype}")
				continue
			
			# Create index
			column_list = ", ".join(columns)
			frappe.db.sql("""
				CREATE INDEX {index_name} 
				ON `tab{doctype}` ({column_list})
			""".format(
				index_name=index_name,
				doctype=doctype,
				column_list=column_list
			))
			
			frappe.db.commit()
			frappe.log_error(f"Created index {index_name} on {doctype}")
			
		except Exception as e:
			frappe.log_error(f"Error creating index {index_name} on {doctype}: {str(e)}")
			# Continue with next index
			continue
	
	frappe.msgprint("Department IR indexes created successfully")

