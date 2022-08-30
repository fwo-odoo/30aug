# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'EDI Invoicing',
    'version': '1.0',
    'category': 'Tools',
    'description': """
Allows Exporting EDI Invoices to True Commerce
==============================================================
EDI Invoice Export (810)
The 810 Invoice document is typically sent in response to an EDI 850 Purchase Order as a request for payment once the goods have shipped or services are provided.
""",
    'author': "Odoo Inc",
    'website': "http://www.odoo.com",
    'license': 'OEEL-1',
    'depends': ['account', 'edi_sale_spscommerce'],
    'data': [
        'data/edi_invoice_data.xml',
        'views/account_move_views.xml',
        'views/account_tax_views.xml',
        'views/res_partner_views.xml',
    ],
    'demo': [],
    'installable': True,
}
