import sys
import os

# Ensure we can import the app modules if run effectively
if __name__ == "__main__":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

import frappe
from frappe.utils import now
import time
try:
    from jewellery_erpnext.jewellery_erpnext.performance.department_ir_logic import process_issue_optimized
except ImportError:
    # If run as script and path not set yet (should not happen if above block runs)
    pass

def generate_mock_data(operation_count=100):
    """
    Generates a dummy Department IR with 'operation_count' lines.
    Does not insert into DB to avoid side effects, unless force=True.
    Actually we need to insert to test the logic that reads from DB.
    So we will Create Test Data and then cleaning up?
    Or just provide the script for them to run on a Test Site.
    """
    frappe.msgprint("Generating Mock Data...")
    
    # Prerequisite: We need valid Company, Department, Items.
    # We assume they exist or we pick the first ones.
    company = frappe.db.get_value("Company", is_default=1) or frappe.get_all("Company")[0].name
    department = frappe.get_all("Department")[0].name
    next_dept = frappe.get_all("Department")[1].name
    
    # Create Dummy MWO and MOP?
    # This is complex.
    # Better strategy: Allow user to pick an EXISTING Department IR and "Duplicate" it X times in memory to simulate load?
    pass

def test_performance(ir_name=None):
    """
    Run the optimized logic on an existing IR (in Draft) and measure time.
    Usage: bench execute jewellery_erpnext.jewellery_erpnext.performance.test_performance.test_performance --args "['IR-12345']"
    """
    if not ir_name:
        print("Please provide an IR Name")
        return

    doc = frappe.get_doc("Department IR", ir_name)
    
    # Mocking massive data if it's small
    original_len = len(doc.department_ir_operation)
    target_count = 700
    if original_len < target_count and original_len > 0:
        print(f"Inflating data from {original_len} to {target_count} operations (InMemory)...")
        # We duplicate rows
        import copy
        base_row = doc.department_ir_operation[0]
        for i in range(target_count - original_len):
            new_row = copy.deepcopy(base_row)
            new_row.name = None
            new_row.idx = len(doc.department_ir_operation) + 1
            # We need unique MWO/MOP?
            # If logic relies on unique DB records, this mock fails.
            # Our logic does fetch MOP from DB.
            # So inflating in memory won't work for DB-bound logic tests without real DB data.
            doc.append("department_ir_operation", new_row)
            
    print(f"Starting Performance Test on {doc.name} with {len(doc.department_ir_operation)} operations.")
    start_time = time.time()
    
    # Run Sync (Simulate what Background Job does)
    try:
        # We start transaction to rollback later
        # frappe.db.begin() would be good but we might want to see results.
        # Let's run it and user can Cancel/Delete if this is test site.
        
        if doc.type == "Issue":
            process_issue_optimized(doc)
        else:
            # process_receive_optimized(doc)
            pass
            
        end_time = time.time()
        print(f"Success! Time Taken: {end_time - start_time:.2f} seconds")
        
    except Exception as e:
        frappe.log_error("Perf Test Failed", str(e))
        print(f"Failed: {str(e)}")
        # frappe.db.rollback()

    # Note: This script modifies DB. Run on Test Site only.

if __name__ == "__main__":
    try:
        frappe.init(site="site1.local") # Default to site1.local, or change as needed
        frappe.connect()
    except Exception as e:
        print(f"Warning: Could not connect to Frappe DB: {e}")
        print("Continuing without DB connection (imports will work, but DB calls will fail).")

    if len(sys.argv) > 1:
        test_performance(sys.argv[1])
    else:
        print("Usage: python test_performance.py <IR_NAME>")
