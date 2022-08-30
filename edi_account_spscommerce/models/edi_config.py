# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from lxml import etree as ET # DOC : https://lxml.de/api/index.html
from math import ceil

import datetime
import logging
import os
import pprint

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)
EDI_DATE_FORMAT = '%Y-%m-%d'

class SyncDocumentType(models.Model):

    _inherit = 'sync.document.type'

    doc_code = fields.Selection(selection_add=[
                                ('export_invoice_xml', '810 - Export Invoice (SPS Commerce XML)')],
                                ondelete = {'export_invoice_xml': 'cascade'})



    def make_invoice_line_xml_data(self, invoice, inv_root):
        line_count = 0
        for line in invoice.invoice_line_ids.filtered(lambda r: r.display_type not in ['line_section', 'line_note']):
            line_item = ET.Element('LineItem')
            invoice_line = ET.SubElement(line_item, 'InvoiceLine')
            ET.SubElement(invoice_line, 'LineSequenceNumber').text = line.x_line_sequence_number or ''
            ET.SubElement(invoice_line, 'BuyerPartNumber').text = line.x_buyer_part_number or ''
            ET.SubElement(invoice_line, 'VendorPartNumber').text = line.x_vendor_part_number or ''
            barcode = line.sale_line_ids[0].x_consumer_package_code if line.sale_line_ids else line.product_id.barcode
            ET.SubElement(invoice_line, 'ConsumerPackageCode').text = barcode[:13] if barcode else ''
            ET.SubElement(invoice_line, 'EAN').text = line.product_id.x_ean or ''
            ET.SubElement(invoice_line, 'GTIN').text = line.product_id.x_gtin or ''
            product_id_block = ET.SubElement(invoice_line, 'ProductID')
            ET.SubElement(product_id_block, 'PartNumber').text = line.x_part_number or ''
            ET.SubElement(invoice_line, 'InvoiceQty').text = str(float(ceil(line.x_qty_cases))) if line.product_uom_id.x_edi_code == 'CA' else str(line.quantity) or '0'
            ET.SubElement(invoice_line, 'InvoiceQtyUOM').text = line.product_uom_id.x_edi_code or 'EA'
            price = line.x_case_price if line.partner_id.x_price_in_cases else line.price_unit
            ET.SubElement(invoice_line, 'PurchasePrice').text = str(round(price, 2)) or '0'

            # ET.SubElement(product_id, 'ShipQty').text = str(line.qty_delivered') or ''
            # ET.SubElement(product_id, 'ShipQtyUOM').text = line.sale_line_ids[0].product_uom.name if line.sale_line_ids else line.product_uom_id.name

            # invoice_line = ET.SubElement(line_item, 'InvoiceLine')
            physical_details = ET.SubElement(line_item, 'PhysicalDetails')
            ET.SubElement(physical_details, 'PackSize').text = str(line.product_id.packaging_ids[0].qty) if line.product_id.packaging_ids else '1'
            ET.SubElement(physical_details, 'PackValue').text = str(line.product_id.packaging_ids[0].qty) if line.product_id.packaging_ids else '1'
            ET.SubElement(physical_details, 'PackUOM').text = 'EA'

            taxes_line = ET.SubElement(line_item, 'Taxes')
            tax_code ='LS'
            if line.tax_ids and line.tax_ids[0].x_edi_taxcode:
                tax_code = line.tax_ids[0].x_edi_taxcode
            ET.SubElement(taxes_line, 'TaxTypeCode').text = tax_code
            ET.SubElement(taxes_line, 'TaxAmount').text = str(round(line.price_subtotal * sum(line.tax_ids.mapped('amount')) / 100, 2)) or ''
            ET.SubElement(taxes_line, 'RelationshipCode').text = 'A'

            product_or_item_description = ET.SubElement(line_item, 'ProductOrItemDescription')
            ET.SubElement(product_or_item_description, 'ProductCharacteristicCode').text = '08'
            ET.SubElement(product_or_item_description, 'ProductDescription').text = line.name or 'Item Description'

            # x_charges_allowances_line = ET.SubElement(line_item, 'ChargesAllowances')

            line_count = line_count + 1
            inv_root.append(line_item)

        return line_count

    def prepare_payment_terms(self, payment_terms, text_payment_terms, invoice_date):

        if text_payment_terms:
            terms_list = [term.split(':') for term in text_payment_terms.splitlines()]
        else:
            text_payment_terms = ''
        ET.SubElement(payment_terms, 'TermsType').text = [i[1].strip() for i in terms_list if i[0] == 'Terms Type'][0] if text_payment_terms else ''
        ET.SubElement(payment_terms, 'TermsBasisDateCode').text = [i[1].strip() for i in terms_list if i[0] == 'Basis Date Code'][0] if text_payment_terms else ''
        ET.SubElement(payment_terms, 'TermsDiscountPercentage').text = [i[1].strip() for i in terms_list if i[0] == 'Discount Percentage'][0] if text_payment_terms else ''
        ET.SubElement(payment_terms, 'TermsDiscountDate').text = [i[1].strip() for i in terms_list if i[0] == 'Discount Date'][0] if text_payment_terms \
                                                                else (invoice_date + datetime.timedelta(days=30)).strftime(EDI_DATE_FORMAT)
        ET.SubElement(payment_terms, 'TermsDiscountDueDays').text = [i[1].strip() for i in terms_list if i[0] == 'Discount Due Days'][0] if text_payment_terms else '30'
        ET.SubElement(payment_terms, 'TermsNetDueDate').text = [i[1].strip() for i in terms_list if i[0] == 'Net Due Date'][0]  if text_payment_terms \
                                                                else (invoice_date + datetime.timedelta(days=30)).strftime(EDI_DATE_FORMAT)
        ET.SubElement(payment_terms, 'TermsNetDueDays').text = [i[1].strip() for i in terms_list if i[0] == 'Net Due Days'][0] if text_payment_terms else ''
        ET.SubElement(payment_terms, 'TermsDescription').text = [i[1].strip() for i in terms_list if i[0] == 'Terms Description'][0] if text_payment_terms else 'Net 30'

        return payment_terms

    def prepare_FOB_related_instruction(self, FOB_related_instruction, text_payment_terms):

        if text_payment_terms:
            terms_list = [term.split(':') for term in text_payment_terms.splitlines()]
        else:
            text_payment_terms = ''
        ET.SubElement(FOB_related_instruction, 'FOBPayCode').text = [i[1].strip() for i in terms_list if i[0] == 'FOB Pay Code'][0] if 'FOB Pay Code' in text_payment_terms else ''
        ET.SubElement(FOB_related_instruction, 'FOBLocationQualifier').text = [i[1].strip() for i in terms_list if i[0] == 'FOB Location Qualifier'][0] if 'FOB Location Qualifier' in text_payment_terms else ''
        ET.SubElement(FOB_related_instruction, 'FOBLocationDescription').text = [i[1].strip() for i in terms_list if i[0] == 'FOB Location Description'][0] if 'FOB Location Description' in text_payment_terms else ''

        return FOB_related_instruction

    def make_invoice_xml_data(self, invoice):
        inv_root = ET.Element('Invoice')
        header = ET.SubElement(inv_root, 'Header')

        invoice_header = ET.SubElement(header, 'InvoiceHeader')
        partner = invoice.partner_id
        source_so = self.env['sale.order'].search([('name', '=', invoice.invoice_origin)], limit=1)
        ET.SubElement(invoice_header, 'TradingPartnerId').text = partner.trading_partnerid or ''
        ET.SubElement(invoice_header, 'InvoiceNumber').text = ('INV%s' % source_so.x_po_number[:12]) if source_so and source_so.x_po_number else invoice.name
        ET.SubElement(invoice_header, 'TsetPurposeCode').text = invoice.x_tset_purpose_code or ''
        ET.SubElement(invoice_header, 'InvoiceDate').text = invoice.invoice_date and invoice.invoice_date.strftime(EDI_DATE_FORMAT) or ''
        ET.SubElement(invoice_header, 'InvoiceTime').text = invoice.invoice_date and invoice.invoice_date.strftime('%H:%M:%S') or ''
        ET.SubElement(invoice_header, 'PurchaseOrderDate').text =  source_so.date_order and source_so.date_order.strftime(EDI_DATE_FORMAT) or ''
        ET.SubElement(invoice_header, 'PurchaseOrderNumber').text = source_so.x_po_number or ''
        ET.SubElement(invoice_header, 'Department').text = source_so.x_department or ''
        ET.SubElement(invoice_header, 'Vendor').text = source_so.x_vendor or ''

        date = source_so.commitment_date or source_so.x_requested_pickup_date or source_so.x_additional_date or source_so.expected_date or fields.Date.today()
        ET.SubElement(invoice_header, 'ShipDate').text = date.strftime(EDI_DATE_FORMAT) or ''

        payment_terms = ET.SubElement(header, 'PaymentTerms')
        payment_terms = self.prepare_payment_terms(payment_terms, invoice.x_customer_payment_terms, invoice.invoice_date)

        dates = ET.SubElement(header, 'Dates')
        ET.SubElement(dates, 'DateTimeQualifier').text = '002'  # Code for: Requested Delivery
        if source_so.x_date_time_qualifier == '002':
            date = source_so.commitment_date
        elif source_so.x_date_time_qualifier == '118':
            date = source_so.x_requested_pickup_date
        else:
            date = source_so.x_additional_date
        if not date:
            date = fields.Datetime.now()
        ET.SubElement(dates, 'Date').text = date.strftime(EDI_DATE_FORMAT) or ''


        FOB_related_instruction = ET.SubElement(header, 'FOBRelatedInstruction')
        FOB_related_instruction = self.prepare_FOB_related_instruction(FOB_related_instruction, invoice.x_customer_payment_terms)

        carrier_info = ET.SubElement(header, 'CarrierInformation')
        ET.SubElement(carrier_info, 'CarrierTransMethodCode').text = 'U'
        ET.SubElement(carrier_info, 'CarrierAlphaCode').text = 'FDEG'
        ET.SubElement(carrier_info, 'CarrierProNumber').text = 'CN'
        ET.SubElement(carrier_info, 'BillOfLadingNumber').text = 'CN'


        lines = invoice.invoice_line_ids.filtered(lambda r: r.display_type not in ['line_section', 'line_note'])
        uom_code = lines[0].product_uom_id.x_edi_code
        qty_field_name = 'x_qty_cases' if uom_code == 'CA' else 'quantity' or '0'

        quantity_totals = ET.SubElement(header, 'QuantityTotals')
        ET.SubElement(quantity_totals, 'QuantityTotalsQualifier').text = 'SQT'
        ET.SubElement(quantity_totals, 'Quantity').text = str(float(ceil(sum(lines.mapped(qty_field_name))))) or '1'
        ET.SubElement(quantity_totals, 'QuantityUOM').text = uom_code or 'EA'

        if source_so.partner_invoice_id:
            address = ET.SubElement(header, 'Address')
            ET.SubElement(address, 'AddressTypeCode').text = 'BT'
            ET.SubElement(address, 'LocationCodeQualifier').text = source_so.partner_invoice_id.x_location_code_qualifier or '9'
            ET.SubElement(address, 'AddressLocationNumber').text = source_so.partner_invoice_id.x_address_location_number or ''
            ET.SubElement(address, 'AddressName').text = source_so.partner_invoice_id.name or ''
            ET.SubElement(address, 'Address1').text = source_so.partner_invoice_id.street or ''
            ET.SubElement(address, 'Address2').text = source_so.partner_invoice_id.street2 or ''
            ET.SubElement(address, 'City').text = source_so.partner_invoice_id.city or ''
            ET.SubElement(address, 'State').text = source_so.partner_invoice_id.state_id.code or ''
            ET.SubElement(address, 'PostalCode').text = source_so.partner_invoice_id.zip or ''
            ET.SubElement(address, 'Country').text = source_so.partner_invoice_id.country_id.code or ''

        if source_so.partner_shipping_id:
            address = ET.SubElement(header, 'Address')
            ET.SubElement(address, 'AddressTypeCode').text = 'ST'
            ET.SubElement(address, 'LocationCodeQualifier').text = source_so.partner_shipping_id.x_location_code_qualifier or '9'
            ET.SubElement(address, 'AddressLocationNumber').text =  source_so.partner_shipping_id.x_address_location_number or ''
            ET.SubElement(address, 'AddressName').text = source_so.partner_shipping_id.name or ''
            ET.SubElement(address, 'Address1').text = source_so.partner_shipping_id.street or ''
            ET.SubElement(address, 'Address2').text = source_so.partner_shipping_id.street2 or ''
            ET.SubElement(address, 'City').text = source_so.partner_shipping_id.city or ''
            ET.SubElement(address, 'State').text = source_so.partner_shipping_id.state_id.code or ''
            ET.SubElement(address, 'PostalCode').text = source_so.partner_shipping_id.zip or ''
            ET.SubElement(address, 'Country').text = source_so.partner_shipping_id.country_id.code or ''

        if source_so.company_id:
            address = ET.SubElement(header, 'Address')
            ET.SubElement(address, 'AddressTypeCode').text = 'RI'
            ET.SubElement(address, 'LocationCodeQualifier').text = source_so.company_id.partner_id.x_location_code_qualifier or '9'
            ET.SubElement(address, 'AddressLocationNumber').text = source_so.company_id.partner_id.x_address_location_number or ''
            ET.SubElement(address, 'AddressName').text = source_so.company_id.name or ''
            ET.SubElement(address, 'Address1').text = source_so.company_id.street or ''
            ET.SubElement(address, 'Address2').text = source_so.company_id.street2 or ''
            ET.SubElement(address, 'City').text = source_so.company_id.city or ''
            ET.SubElement(address, 'State').text = source_so.company_id.state_id.code or ''
            ET.SubElement(address, 'PostalCode').text = source_so.company_id.zip or ''
            ET.SubElement(address, 'Country').text = source_so.company_id.country_id.code or ''

        references = ET.SubElement(header, 'References')
        ET.SubElement(references, 'ReferenceQual').text = 'MR'
        ET.SubElement(references, 'ReferenceID').text = invoice.x_merch_type_code or ''

        # Nodes below are not currently required by any trading partners but may be in the future ----------------------
        # taxes_line = ET.SubElement(line_item, 'Taxes')
        # tax_code ='BE'
        # if line.tax_ids and line.tax_ids[0].x_edi_taxcode:
        #     tax_code = line.tax_ids[0].x_edi_taxcode
        # ET.SubElement(taxes_line, 'TaxTypeCode').text = tax_code
        # ET.SubElement(taxes_line, 'TaxAmount').text = str(round(line.price_subtotal * sum(line.tax_ids.mapped('amount')) / 100, 2)) or ''
        # ET.SubElement(taxes_line, 'RelationshipCode').text = 'A'

        # all_taxes = invoice.invoice_line_ids.mapped('tax_ids').mapped('x_edi_taxcode') or ''

        # taxes_head = ET.SubElement(header, 'Taxes')
        # ET.SubElement(taxes_head, 'TaxTypeCode').text = all_taxes[0] if all_taxes else 'BE'
        # ET.SubElement(taxes_head, 'TaxPercent').text = str(round(sum([line.price_subtotal * \
        #                                                              sum(line.tax_ids.mapped('amount')) / 100 \
        #                                                              for line in invoice.invoice_line_ids]), 2))
        # ET.SubElement(taxes_head, 'RelationshipCode').text = 'O'
        # ET.SubElement(taxes_head, 'TaxID').text = str(self.env.company.vat or '').replace(" ", "")

        for charge in source_so.x_charges_allowances:
            x_charges_allowances = ET.SubElement(header, 'ChargesAllowances')
            ET.SubElement(x_charges_allowances, 'AllowChrgIndicator').text = charge.indicator or ''
            ET.SubElement(x_charges_allowances, 'AllowChrgCode').text = charge.code or ''
            ET.SubElement(x_charges_allowances, 'AllowChrgAmt').text = str(charge.amount) or ''
            ET.SubElement(x_charges_allowances, 'AllowChrgPercentQual').text = charge.percent_qualifier or ''
            ET.SubElement(x_charges_allowances, 'AllowChrgPercent').text = str(charge.percent) or ''
            ET.SubElement(x_charges_allowances, 'AllowChrgHandlingCode').text = charge.handling_code or ''

        line_count = self.make_invoice_line_xml_data(invoice, inv_root)

        summary = ET.SubElement(inv_root, 'Summary')
        ET.SubElement(summary, 'TotalAmount').text = str(round(invoice.amount_residual, 2)) or '0'
        ET.SubElement(summary, 'TotalLineItemNumber').text = str(line_count) or '0'
        ET.SubElement(summary, 'TotalSalesAmount').text = str(round(invoice.amount_total, 2)) or '0'
        ET.SubElement(summary, 'TotalTermsDiscountAmount').text =  str(round(source_so.amount_undiscounted - source_so.amount_untaxed, 2)) or '0'   # Always will be 0

        return inv_root

    @api.model
    def _do_export_invoice_xml(self, conn, sync_action_id, values):
        '''
        Performs the document synchronization for the new document code
        @param conn : sftp/ftp connection class.
        @param sync_action_id: recordset of type `edi.sync.action`
        @param values:dict of values that may be useful to various methods

        @return bool : return bool (True|False)
        '''
        conn._connect()
        conn.cd(sync_action_id.dir_path)

        # Get sale invoices to be sent to edi:
        # Get individual records passed when SO hits action_post()
        # or get all pending records when user runs the synchronization action manually
        invoices = values.get('records') or self.env['account.move'].sudo().search([('state', '=', 'posted'),
                                                                                    ('x_edi_status', '=', 'pending'),
                                                                                    ('partner_id.x_outbound_edi_inv', '=', True)
                                                                                    ])
        invoices._check_edi_required_fields()

        for invoice in invoices:
            invoice_data = self.make_invoice_xml_data(invoice)
            invoice_data = ET.ElementTree(invoice_data)

            if invoice_data:
                filename = '810_invoice_%s.xml' % (invoice.ref or invoice.name.replace('/', '_'))
                with open(filename, 'wb') as file:
                    invoice_data.write(file, pretty_print=True)
                try:
                    with open(filename, 'rb') as file:
                        conn.upload_file(filename, file)
                        file.close()
                    # Update EDI Status to sent
                    invoice.write({'x_edi_status': 'sent', 'x_edi_date': fields.Datetime.now()})
                    invoice.sudo().message_post(body=_('Invoice file created on the EDI server %s' % filename))
                    _logger.info('Invoice file created on the server path of %s/%s' % (sync_action_id.dir_path, filename))
                except Exception as e:
                    invoice.write({'x_edi_status': 'fail'})
                    _logger.error('file not uploaded %s' % e)
                os.remove(filename)
            self.flush()
        conn._disconnect()
        return True
