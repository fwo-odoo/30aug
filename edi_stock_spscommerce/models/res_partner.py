# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _

class Partner(models.Model):
    _inherit = 'res.partner'

    x_outbound_edi_asn = fields.Boolean(string='Outbound 856 ASN',
                                        help='True if the contact sends outbound Advanced Shipping Notice to the EDI')
