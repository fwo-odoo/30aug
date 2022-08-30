# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

class Product(models.Model):
    _inherit = 'product.template'

    x_ean = fields.Char(string='EAN',
                        help='International Article Number, aka European Article Number, which is the European equivalent of the United States UPC[Universal Product Code]')

    x_gtin = fields.Char(string='GTIN',
                        help='Global Trade Item Number which is an item identifier that encompasses all product identification numbers such as UPC, EAN, ITF, etc. and can be assigned at various packing levels')


class ProductPackaging(models.Model):
    _inherit = 'product.packaging'

    x_package_price = fields.Monetary(currency_field='x_company_currency_id',
                            string='Price',
                            help='Package Price')

    x_company_currency_id = fields.Many2one('res.currency', readonly=True, default=lambda x: x.env.company.currency_id)


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    x_package_id = fields.Many2one('product.packaging', string='Package')
    x_partner_id = fields.Many2one('res.partner', string='Trading Partner', domain="[('is_company', '=', True)]")
    x_inv_partner_id = fields.Many2one('res.partner', string='Invoice Address', help='Invoice address of the trading partner. \
                                        It should only be set if it is different from the Trading Partner column')
    x_product_product = fields.Many2one(related='product_tmpl_id.product_variant_id', string='Product Variant')
