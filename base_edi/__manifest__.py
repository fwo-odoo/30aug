# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'EDI Document Synchronization Base',
    'version': '1.0',
    'category': 'Tools',
    'description': """
Allows you to configure EDI document exchange configurations
==============================================================
You can perform your own EDI XML export and import via FTP.
""",
    'author': "Odoo Inc",
    'website': "http://www.odoo.com",
    'license': 'OEEL-1',
    'depends': ['mail'],
    'data': [
        'security/base_edi_security.xml',
        'security/ir.model.access.csv',
        'views/edi_config_view.xml',
        'views/res_partner_view.xml',
        'data/ir_cron_data.xml',
    ],
    'demo': [],
    'installable': True,
}
