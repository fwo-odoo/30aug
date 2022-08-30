# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

class AccountPaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    x_description = fields.Char(string='Description')
    x_type = fields.Char(string='Type')
    x_basis_date_code = fields.Char(string='Basis Date Code')
    x_discount_percentage = fields.Char(string='Discount Percentage')
    x_discount_date = fields.Char(string='Discount Date')
    x_discount_due_days = fields.Char(string='Discount Due Days')
    x_net_due_date = fields.Char(string='Net Due Date')
    x_net_due_days = fields.Char(string='Net Due Days')