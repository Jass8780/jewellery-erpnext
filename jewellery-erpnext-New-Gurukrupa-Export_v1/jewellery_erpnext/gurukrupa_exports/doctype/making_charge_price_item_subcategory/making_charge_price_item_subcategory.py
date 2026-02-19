# Copyright (c) 2023, Nirali and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MakingChargePriceItemSubcategory(Document):
	pass


def on_doctype_update():
	# Add index on this doctype's own table only (not Finding Subcategory).
	frappe.db.add_index("Making Charge Price Item Subcategory", ["subcategory"])
