
import frappe
from jewellery_erpnext.jewellery_erpnext.doc_events.stock_entry import before_validate as original_before_validate
from jewellery_erpnext.jewellery_erpnext.doc_events.stock_entry import onsubmit as original_onsubmit
# Note: hooks.py refers to .customization.stock_entry.stock_entry.before_validate
from jewellery_erpnext.jewellery_erpnext.customization.stock_entry.stock_entry import before_validate as custom_before_validate
from jewellery_erpnext.jewellery_erpnext.customization.stock_entry.stock_entry import on_submit as custom_onsubmit

def before_validate_wrapper(doc, method):
    if doc.flags.get("skip_heavy_hooks"):
        return
    original_before_validate(doc, method)

def onsubmit_wrapper(doc, method):
    if doc.flags.get("skip_heavy_hooks"):
        return
    original_onsubmit(doc, method)
    
def custom_before_validate_wrapper(doc, method):
    if doc.flags.get("skip_heavy_hooks"):
        return
    custom_before_validate(doc, method)

def custom_onsubmit_wrapper(doc, method):
    if doc.flags.get("skip_heavy_hooks"):
        return
    custom_onsubmit(doc, method)
