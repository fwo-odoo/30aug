# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

class Partner(models.Model):
    _inherit = 'res.partner'

    x_outbound_edi_inv = fields.Boolean(string='Outbound 810 Invoice',
                                        help='Whether the contact sends outbound 810 Invoices to the EDI.')
