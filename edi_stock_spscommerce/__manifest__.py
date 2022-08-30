# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'EDI Stock',
    'version': '1.0',
    'category': 'Tools',
    'description': """
Allows Exporting EDI Shipments to SPS Commerce
==============================================================
EDI Shipment Export (856)
The primary purpose of the EDI 856 advance ship notice (ASN) is to provide detailed information about a pending delivery of goods. 
The ASN describes the contents that have been shipped as well the carrier moving the order, the size of the shipment, ship date and in some cases estimated delivery date.
""",
    'author': "Odoo Inc",
    'website': "http://www.odoo.com",
    'license': 'OEEL-1',
    'depends': ['delivery', 'edi_sale_spscommerce'],
    'data': [
        'data/edi_stock_data.xml',
        'views/res_partner_views.xml',
        'views/stock_picking_views.xml',
    ],
    'demo': [],
    'installable': True,
}
