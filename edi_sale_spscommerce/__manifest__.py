# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'EDI Sale',
    'version': '1.0',
    'category': 'Tools',
    'description': """
Allows Importing EDI Purchase Orders to SPS Commerce
========================================================
EDI Purchase Import (850)
An EDI 850 is a type of electronic data interchange transaction set that contains details about an order. 
Also known as an electronic purchase order, an EDI 850 is usually sent to a vendor as the first step in the ordering process.
""",
    'author': "Odoo Inc",
    'website': "http://www.odoo.com",
    'license': 'OEEL-1',
    'depends': ['account', 'base_edi', 'sale_management', 'stock'],
    'data': [
        'data/actions.xml',
        'data/edi_sale_data.xml',
        'views/charge_allowance.xml',
        'views/partner_views.xml',
        'views/payment_term_views.xml',
        'views/product_views.xml',
        'views/sale_views.xml',
        'views/uom_views.xml',
        'security/ir.model.access.csv',
    ],
    'demo': [],
    'installable': True,
}
