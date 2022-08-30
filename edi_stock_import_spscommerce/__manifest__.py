# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'EDI Stock Import',
    'version': '1.0',
    'category': 'Tools',
    'description': """
Allows Importing EDI Shipments to SPS Commerce
==============================================================
EDI Shipment Import (945)
The EDI 945 transaction set, referred to as Warehouse Shipping Advice transaction, provides confirmation of a shipment. 
This transaction is used by a warehouse to notify a trading partner that a shipment was made.
""",
    'author': "Odoo Inc",
    'website': "http://www.odoo.com",
    'license': 'OEEL-1',
    'depends': ['edi_stock_spscommerce'],
    'data': [
        'data/actions.xml',
        'data/edi_stock_data.xml',
        'views/res_partner_views.xml',
        'views/stock_picking_views.xml',
    ],
    'demo': [],
    'installable': True,
}
