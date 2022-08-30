# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _

class Partner(models.Model):
    _inherit = 'res.partner'

    x_inbound_edi_warehouse = fields.Boolean(string='Inbound 945 WSA',
                                             help='True if the contact receives Warehouse Shipping Advice from the EDI')
