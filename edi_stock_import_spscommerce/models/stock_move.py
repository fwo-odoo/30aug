# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import ast
import requests
from odoo.http import request
import json
from odoo import fields, models, api
from odoo.exceptions import UserError
import logging
from datetime import datetime, date
from odoo.exceptions import ValidationError
import re
import os

_logger = logging.getLogger(__name__)

EDI_DATE_FORMAT = '%Y-%m-%d'

class StockMove(models.Model):
    _inherit = 'stock.move'

    x_consumer_package_code = fields.Char(string='Consumer Package Code (EDI)',
                              help='Consumer Package Code passed from the EDI. We store it because sometimes it contains leading or training zeros that we need to transmit outbound. When searching for a product sometimes we need to strip these zeros to find the match.')
    x_line_sequence_number = fields.Char(string='Line Sequence Number',
                              help='For an initiated document, this is a unique number for the line item[s]. For a return transaction, this number should be the same as what was received from the source transaction. Example: You received a Purchase Order with the first LineSequenceNumber of 10. You would then send back an Invoice with the first LineSequenceNumber of 10')
    x_buyer_part_number = fields.Char(string='Buyer Part Number',
                              help='Buyer\'s primary product identifier')
    x_vendor_part_number = fields.Char(string='Vendor Part Number',
                              help='Vendor\'s primary product identifier')
    x_part_number = fields.Char(string='Part Number',
                              help='Vendor\'s part number. Belongs to the <ProductID> field on the EDI file.')
    x_done_cases = fields.Float(string='Done Cases', compute='_compute_done_cases')
    x_ordered_cases = fields.Float(string='Ordered Cases', compute='_compute_ordered_cases')
    x_edi_uom = fields.Many2one(string='EDI UoM', comodel_name='uom.uom', copy=True)

    @api.depends('product_uom_qty')
    def _compute_done_cases(self):
        for record in self:
            if record.product_uom_qty and record.product_id and record.product_id.packaging_ids and record.product_id.packaging_ids[0].qty:
                record.x_done_cases = float(record.product_uom_qty / record.product_id.packaging_ids[0].qty)
            else:
                record.x_done_cases = record.product_uom_qty

    @api.depends('product_id.packaging_ids.qty')
    def _compute_ordered_cases(self):
        for record in self:
            if record.product_id.packaging_ids and record.product_id.packaging_ids[0].qty:
                record.x_ordered_cases = float(record.product_uom_qty / record.product_id.packaging_ids[0].qty)
            else:
                record.x_ordered_cases = 0


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # x_done_cases = fields.Float(related='move_id.x_done_cases')
    # x_ordered_cases = fields.Float(related='move_id.x_ordered_cases')
    # x_edi_uom = fields.Many2one(related='move_id.x_edi_uom')

    x_consumer_package_code = fields.Char(string='Consumer Package Code (EDI)',
                              help='Consumer Package Code passed from the EDI. We store it because sometimes it contains leading or training zeros that we need to transmit outbound. When searching for a product sometimes we need to strip these zeros to find the match.',
                              related='move_id.x_consumer_package_code')

    x_line_sequence_number = fields.Char(string='Line Sequence Number',
                              help='For an initiated document, this is a unique number for the line item[s]. For a return transaction, this number should be the same as what was received from the source transaction. Example: You received a Purchase Order with the first LineSequenceNumber of 10. You would then send back an Invoice with the first LineSequenceNumber of 10')
                              # related='move_id.x_line_sequence_number')

    x_buyer_part_number = fields.Char(string='Buyer Part Number',
                              help='Buyer\'s primary product identifier',
                              related='move_id.x_buyer_part_number')

    x_vendor_part_number = fields.Char(string='Vendor Part Number',
                              help='Vendor\'s primary product identifier',
                              related='move_id.x_vendor_part_number')

    x_part_number = fields.Char(string='Part Number',
                              help='Vendor\'s part number. Belongs to the <ProductID> field on the EDI file.',
                              related='move_id.x_part_number')

    x_done_cases = fields.Float(related='move_id.x_done_cases')
    x_ordered_cases = fields.Float(related='move_id.x_ordered_cases')
    x_edi_uom = fields.Many2one(comodel_name='uom.uom',
                                related='move_id.x_edi_uom')


    # def create(self, vals):
    #     res = super(StockMoveLine, self).create(vals)
    #     for record in res:
    #         if record.move_id.picking_id and record.move_id.picking_id.sale_id:
    #             sale = record.move_id.picking_id.sale_id
    #             sale_line = sale.order_line.filtered(lambda r: r.product_id == record.product_id)
    #             if len(sale_line) == 1:
    #                 record.write({
    #                     'x_line_sequence_number': sale_line.x_line_sequence_number,
    #                     'x_vendor_part_number': sale_line.x_vendor_part_number,
    #                     'x_buyer_part_number': sale_line.x_buyer_part_number,
    #                     'x_part_number': sale_line.x_part_number,
    #                     'x_edi_uom': sale_line.product_uom.id,
    #                     'x_consumer_package_code': sale_line.x_consumer_package_code,
    #                 })
    #     return res

    def write(self, vals):
        res = super(StockMoveLine, self).write(vals)
        for record in self:
            if not record.x_line_sequence_number:
                existing_nums = self.picking_id.move_line_ids_without_package.sorted(
                    key=lambda r: int(r.x_line_sequence_number), reverse=True).mapped('x_line_sequence_number')
                num = str(int(existing_nums[0]) + 1) if existing_nums else '1'
                record.write({'x_line_sequence_number': num})
        return res


