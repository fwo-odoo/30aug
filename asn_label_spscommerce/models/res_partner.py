# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _

class Partner(models.Model):
    _inherit = 'res.partner'

    x_label_id = fields.Char(string='Label ID',
                             help='Identification number for the label template used by SPS Commerce API')
