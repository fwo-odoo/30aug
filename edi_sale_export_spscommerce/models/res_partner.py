# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

class Partner(models.Model):
    _inherit = 'res.partner'

    x_outbound_edi_poa = fields.Boolean(string='Outbound 855 POA',
                                        help='True if the contact sends outbound Sale Order Acknowledgements to the EDI.')
