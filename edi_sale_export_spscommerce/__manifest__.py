# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'EDI Sale Export',
    'version': '1.0',
    'category': 'Tools',
    'description': """
Allows Exporting EDI Purchase Order Acknowledgements to SPS Commerce
===================================================================
EDI Purchase Export (855)
An EDI 855 Purchase Order Acknowledgement is an EDI transaction set normally sent by a seller to a buyer in response to an EDI 850 Purchase Order. 
In addition to confirming the receipt of a new order, the document tells the buyer if the purchase order was accepted, required changes, or was rejected.
""",
    'author': "Odoo Inc",
    'website': "http://www.odoo.com",
    'license': 'OEEL-1',
    'depends': ['edi_sale_spscommerce'],
    'data': [
        'data/edi_sale_data.xml',
        'views/res_partner_views.xml',
    ],
    'demo': [],
    'installable': True,
}
