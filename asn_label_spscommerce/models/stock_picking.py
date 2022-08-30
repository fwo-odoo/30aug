# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import ast
import base64
import json
import logging
import os
import requests

from odoo import fields, models, api, _
from datetime import datetime, date
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

EDI_DATE_FORMAT = '%Y-%m-%d'


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_asn_data_zpl = fields.Char(string='ASN Label (ZPL)', help='ASN Label data in ZPL format to be used in printing the report.')

    def _get_report_filename(self):
        return 'ASN_%s' % self.name

    def print_asn(self):
        # Check that the ASN label is an attachments
        attachment = self.env['ir.attachment'].search([('name', '=', 'ASN_' + self.name + '.zpl'), ('res_id', '=', self.id)])
        if not attachment:
            raise ValidationError('Error: No attachments found. Please generate the ASN label by validating the shipping in PACK stage.')
        return {
            'type': 'ir.actions.act_url',
            'url': "web/content/?download=true&id=%s" % (attachment.id)
            }

    def make_pallets(self):
        lines_without_pallet = self.move_line_ids_without_package.filtered([('result_package_id', '=', None)])
        if lines_without_pallet:
            raise ValidationError('The products need to be shipped with a pallet number. Please put products in Pack.')

        pallets = self.move_line_ids_without_package.mapped('result_package_id')
        pallets_dict = {}

        for pallet in pallets:
            barcodes = ''
            description = ''
            weight = 0
            qty = 0
            lines_on_pallet = self.move_line_ids_without_package.filtered(lambda r: r.result_package_id == pallet)
            for line in lines_on_pallet:
                barcodes += (', %s' % line.product_id.barcode)
                description += (', %s' % line.product_id.name)
                qty += line.qty_done

            pallets_dict[pallet.name] = {'barcodes': barcodes,
                                        'description': description,
                                        'qty': qty,
                                        'weight': weight,
                                        }
        return pallets_dict

    def make_pallets_one_item(self):
        lines_without_pallet = self.move_line_ids_without_package.filtered(lambda r: r.result_package_id == False)
        if lines_without_pallet:
            raise ValidationError('The products need to be shipped with a pallet number. Please put products in Pack.')

        pallets = self.move_line_ids_without_package.mapped('result_package_id')
        pallets_dict = {}

        for pallet in pallets:

            lines_on_pallet = self.move_line_ids_without_package.filtered(lambda r: r.result_package_id == pallet)
            for line in lines_on_pallet:
                barcodes = line.product_id.barcode
                description = pallet.name
                qty = line.qty_done
                vendor_partnumber = line.x_vendor_part_number or 'NA'

            pallets_dict[pallet.name] = {'barcodes': barcodes,
                                        'description': description,
                                        'qty': qty,
                                        'weight': self.x_weight,
                                        'vendor_partnumber': vendor_partnumber,
                                        }
        return pallets_dict

    def get_formatted_data_507d55ae(self):
        """
            Trading Partner ID: Mckesson [Canada]
            Returns a JSON data structure of the necessary data about the current shipping
            that needs to be passed to the SPS commerce API for getting the ASN Label
        """
        # Make sure you have all the API-required fields set before making the request
        are_required_fields_set = self.company_id.partner_id.x_address_location_number \
                                  and self.partner_id.x_address_location_number

        if not are_required_fields_set:
            raise ValidationError('Some fields required by the SPS Commerce API are missing. \
            Please fill Address Location Number on your company\'s address and on the partner\'s address.')

        pallets = self.make_pallets_one_item()
        items_in_pack = []
        for pallet, values in pallets.items():
            new_item = {
                'Item': [{
                    'VendorPartNumber': pallet,
                    'ConsumerPackageCode': values['barcodes'],
                    'ShipQty': values['qty'],
                    'Dates': [{
                            'DateTimeQualifier': '018',
                            'Date': datetime.strftime(datetime.now(), EDI_DATE_FORMAT),
                    }]
                }],
                'ShippingSerialID': self.generate_sscc(pallet),
            }
            items_in_pack.append(new_item)

        data = {
          'Header': {
            'PurchaseOrderNumber': self.sale_id.x_po_number or 'n/a',
            'BillOfLadingNumber': self.x_bill_of_lading_number,
            'Address': [
              {
                'AddressTypeCode': 'SF',
                'AddressLocationNumber':  self.company_id.partner_id.x_address_location_number[:80],
                'AddressName': self.company_id.name[:24],
                'Address1': self.company_id.street[:55],
                'Address2': self.company_id.street2 or '',
                'City': self.company_id.city[:30],
                'State': self.company_id.state_id.code,
                'PostalCode': self.company_id.zip[:15],
              },
              {
                'AddressTypeCode': 'ST',
                'AddressLocationNumber': self.partner_id.x_address_location_number[:80],
                'AddressName': self.partner_id.name[:25],
                'Address1': self.partner_id.street[:55],
                'Address2': self.partner_id.street2 or '',
                'City':  self.partner_id.city[:30],
                'State':  self.partner_id.state_id.code,
                'PostalCode':  self.partner_id.zip[:15],
              }
            ],
            'CarrierInformation': [{
                'CarrierRouting': self.x_carrier_alpha_code[:35]
            }],
          },
          'Pack': items_in_pack
        }
        data = json.dumps(data, indent=4)
        return data



    def get_formatted_data_3413d3da(self):
        """ Trading Partner ID: Loblaw (5010VICS) & Shoppers Drug Mart DC
            Returns a JSON data structure of the necessary data about the current shipping
            that needs to be passed to the SPS commerce API for getting the ASN Label
        """
        # Make sure you have all the API-required fields set before making the request
        # are_required_fields_set = self.company_id.street \
        #                           and self.company_id.partner_id.x_address_location_number \
        #                           and self.x_carrier_alpha_code
        # if not are_required_fields_set:
        #     raise ValidationError('Some fields required by the SPS Commerce API are missing.\n \
        #     Please check Address information and AddressLocationNumber (sender and receiver)')

        pallets = self.make_pallets_one_item()

        items_in_pack = []

        for pallet, values in pallets.items():
            new_item = {
                'PhysicalDetails': [
                    {
                      'PackQualifier': 'OU',
                      'PackValue': values['qty'] or '',
                      'PackWeight': values['weight'] or '',
                    },
                ],
                'Item': [
                    {
                        'GTIN': values['barcodes'] or '',
                        'ProductOrItemDescription': [
                          {
                            'ProductCharacteristicCode': '08',
                            'ProductDescription': pallet,
                          }
                        ],
                    }
                ],
                'ShippingSerialID': self.generate_sscc(pallet),
            }
            items_in_pack.append(new_item)

        data = {
            'Header': {
                'PurchaseOrderNumber': self.sale_id.x_po_number or 'n/a',
                'BillOfLadingNumber': self.x_bill_of_lading_number,
                # 'CarrierProNumber': 'CarrierProNumber',
                'Address': [
                    {
                        'AddressTypeCode': 'SF',
                        'AddressName': self.company_id.name,
                        'Address1': self.company_id.street,
                        'Address2': self.company_id.street2 or '',
                        'City': self.company_id.city,
                        'State': self.company_id.state_id.code,
                        'PostalCode':  self.partner_id.zip,
                    },
                    {
                        'AddressTypeCode': 'ST',
                        'AddressName': self.partner_id.name,
                        'Address1': self.partner_id.street,
                        'Address2': self.partner_id.street2 or '',
                        'City':  self.partner_id.city,
                        'State':  self.partner_id.state_id.code,
                        'PostalCode':  self.partner_id.zip,
                    }
                ],
                'CarrierInformation': [{
                    'CarrierRouting': self.x_carrier_alpha_code
                }],
            },
            'Pack': items_in_pack
        }

        data = json.dumps(data, indent=4)
        return data



    def generate_shipping_label(self, access_token, label_id):
        """Generate Shipping Label, attach to form view and notify followers

        The key data elements included in a GS1-128|UCC-128 Shipping Label include:
            Ship from information
            Ship to information
            Serial Shipping Container Code (referred to as SSCC-18 barcode)
        """
        _logger.info('generate_shipping_label')
        url_pdf = 'https://api.spscommerce.com/label/v1/%s/pdf?url=True' % label_id
        url_zpl = 'https://api.spscommerce.com/label/v1/%s/zpl?mediaType=D' % label_id

        headers = {'Authorization': 'Bearer {}'.format(access_token), 'Content-Type': 'application/pdf'}

        get_formatted_data_by_label = 'get_formatted_data_%s' % label_id
        data = getattr(self, get_formatted_data_by_label)()

        # PDF Format ----------------------------------------------------------
        try:
            resp_pdf = requests.post(url_pdf, headers=headers, data=data)

        except Exception as ex:
            _logger.exception('edi_sps: %s' %(ex))
            raise ValidationError('API for PDF returned status code: %s' % resp_pdf.content)

        try:
            # For pdf format, a url pointing to the label is returned
            resp_dict_str = resp_pdf.content.decode('UTF-8')

            url_dict = ast.literal_eval(resp_dict_str)
            resp_pdf_data = requests.get(url_dict['pdfURL'], headers=headers, stream=True)

        except Exception as ex:
            _logger.exception('edi_sps: %s' %(ex))
            raise ValidationError('API for PDF returned status code: %s' % resp_pdf.content)

        with open('asn_label.pdf', 'xb') as f:
            f.write(resp_pdf_data.content)
            # file = f.read()
            _logger.info('Shipping Label pdf created in the server.')
        with open('asn_label.pdf', 'rb') as f:
            file = f.read()
            f.close()
        if os.path.exists('asn_label.pdf'):
            os.remove('asn_label.pdf')

        if file:
            attachment_data = {
                'name': 'ASN_label_' + self.name,
                'datas': base64.b64encode(file),
                'type': 'binary',
                'res_model': 'mail.mail',
                'mimetype': 'application/pdf',
            }

            # Send email to all followers
            template = self.env.ref('edi_stock_spscommerce.mail_template_shipping_label')
            partners = self.message_follower_ids.mapped('partner_id')
            if partners:
                template.send_mail(res_id=self.id, force_send=True, email_values={'attachment_ids': [(0, 0, attachment_data)], 'recipient_ids': [(4, p.id) for p in partners]})

            #  Link attachment to shipping
            attachment_data.update({'res_model': 'stock.picking', 'res_id': self.id})
            attachment =  self.env['ir.attachment'].create(attachment_data)
            self.write({
                'message_main_attachment_id': attachment.id
            })

        # ZPL Format ----------------------------------------------------------
        try:
            resp_zpl = requests.post(url_zpl, headers=headers, data=data)
        except Exception as ex:
            _logger.exception('edi_sps: %s' %(ex))
            raise ValidationError('API for ZPL returned status code: %s' % resp_zpl.content)

        with open('asn_label.zpl', 'xb') as f:
            f.write(resp_zpl.content)
            _logger.info('Shipping Label zpl created in the server.')

            self.x_asn_data_zpl = resp_zpl.content

        with open('asn_label.zpl', 'rb') as f:
            file = f.read()
            f.close()
        if os.path.exists('asn_label.zpl'):
            os.remove('asn_label.zpl')

        if file:
            attachment_data_zpl = {
                'name': 'ASN_' + self.name + '.zpl',
                'datas': base64.b64encode(file),
                'type': 'binary',
                'res_model': 'stock.picking',
                'mimetype': 'x-application/zpl',
                'res_id': self.id,
            }
        attachment = self.env['ir.attachment'].create(attachment_data_zpl)


    def _action_done(self):
        for picking in self:
            # Check that all required fields are present before validating
            needs_label = picking.partner_id.x_label_id and picking.picking_type_id.sequence_code == 'PACK' and picking.location_dest_id.name == 'Output'
            if needs_label:
                label_id = picking.partner_id.x_label_id
                if not label_id:
                    raise ValidationError('Missing shipping label ID on partner.')
                if not picking.x_bill_of_lading_number or not picking.x_carrier_alpha_code or not picking.x_weight:
                    raise ValidationError('Bill Of Landing Number, Carrier Alpha Code, and Weight are required to generate ASN label.')

            res = super(StockPicking, self)._action_done()

            if needs_label:
                sps_edi_config = picking.env['edi.config'].search([('name', '=', 'SPS Commerce')], limit=1)
                access_token = sps_edi_config.access_token
                picking.generate_shipping_label(access_token=access_token, label_id=label_id)

            return res

