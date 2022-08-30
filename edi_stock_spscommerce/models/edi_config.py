# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import os
import logging
import pprint
import pytz
from datetime import datetime
from lxml import etree as ET # DOC : https://lxml.de/api/index.html
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)
EDI_DATE_FORMAT = '%Y-%m-%d'

class SyncDocumentType(models.Model):

    _inherit = 'sync.document.type'

    doc_code = fields.Selection(selection_add=[
                                ('export_shipping_xml', '856 - Export Shipping Acknowledgement (SPS Commerce XML)'),
                                ('import_shipping_xml', '945 - Import Warehouse Shipping Advice (SPS Commerce XML)')],
                                ondelete={'export_shipping_xml': 'cascade',
                                          'import_shipping_xml': 'cascade'})

    def make_picking_line_xml_data(self, picking, source_so):
        tz = self.env.user.tz or pytz.utc
        line_count = 0
        line_item = ET.Element("OrderLevel")

        order_header = ET.SubElement(line_item, "OrderHeader")
        ET.SubElement(order_header, "PurchaseOrderNumber").text = str(source_so.x_po_number)
        ET.SubElement(order_header, "PurchaseOrderDate").text = datetime.strftime(source_so.date_order, EDI_DATE_FORMAT) or ''
        ET.SubElement(order_header, "Vendor").text = str(source_so.x_vendor)

        pallet_number = ''

        for line in picking.move_line_ids_without_package:
            if not line.result_package_id:
                raise ValidationError("Please assign a package to each line.")

            new_line_pallet_number = line.result_package_id.name or ''
            if new_line_pallet_number != pallet_number:
                pack_level = ET.SubElement(line_item, "PackLevel")

                pallet_number = new_line_pallet_number
                pack = ET.SubElement(pack_level, "Pack")
                ET.SubElement(pack, "PackLevelType").text = 'P'
                ET.SubElement(pack, "ShippingSerialID").text = str(picking.generate_sscc(pallet_number))

                marks_and_numbers_collection = ET.SubElement(pack_level, "MarksAndNumbersCollection")
                ET.SubElement(marks_and_numbers_collection, "MarksAndNumbersQualifier1").text = 'W'
                ET.SubElement(marks_and_numbers_collection, "MarksAndNumbers1").text = pallet_number


            item_level = ET.SubElement(pack_level, "ItemLevel")
            shipment_line = ET.SubElement(item_level, "ShipmentLine")
            ET.SubElement(shipment_line, "LineSequenceNumber").text = line.x_line_sequence_number or ''
            ET.SubElement(shipment_line, "BuyerPartNumber").text = line.x_buyer_part_number or ''
            ET.SubElement(shipment_line, "VendorPartNumber").text = line.x_vendor_part_number or ''
            ET.SubElement(shipment_line, "ConsumerPackageCode").text = line.product_id.barcode or ''
            ET.SubElement(shipment_line, "EAN").text = line.product_id.x_ean or ''
            ET.SubElement(shipment_line, "GTIN").text = line.product_id.x_gtin or ''
            product_id_block = ET.SubElement(shipment_line, 'ProductID')
            # ET.SubElement(product_id_block, 'PartNumber').text = line.x_part_number or ''
            ET.SubElement(shipment_line, "ShipQty").text = str(line.x_done_cases) if line.x_edi_uom.x_edi_code == 'CA' else str(line.qty_done) or '0'
            ET.SubElement(shipment_line, "ShipQtyUOM").text = line.x_edi_uom.x_edi_code or 'EA'

            # ET.SubElement(shipment_line, "OrderQty").text = str(line.x_done_cases) if line.x_edi_uom.x_edi_code == 'CA' else str(line.qty_done) or '0'
            # ET.SubElement(shipment_line, "OrderQtyUOM").text = line.x_edi_uom.x_edi_code or 'EA'

            physical_details = ET.SubElement(item_level, 'PhysicalDetails')
            ET.SubElement(physical_details, 'PackValue').text = str(line.product_id.packaging_ids[0].qty) if line.product_id.packaging_ids else '1'
            ET.SubElement(physical_details, 'PackSize').text = str(line.product_id.packaging_ids[0].qty) if line.product_id.packaging_ids else '1'
            ET.SubElement(physical_details, 'PackUOM').text = line.product_uom_id.x_edi_code or 'EA'

            # ET.SubElement(product_id, "ShipQty").text = str(sum(line.mapped('sale_line_ids.qty_delivered')))
            # ET.SubElement(product_id, "ShipQtyUOM").text = str(line.sale_line_ids[0].product_uom.name if line.sale_line_ids else line.product_uom_id.name)

            product_or_item_description = ET.SubElement(item_level, "ProductOrItemDescription")
            ET.SubElement(product_or_item_description, "ProductCharacteristicCode").text = '08'
            sale_line = source_so.order_line.filtered(lambda r: r.product_id == line.product_id)
            if len(sale_line) == 1:
                description = sale_line.name
            else:
                description = line.product_id.description_sale or 'Item Description'
            ET.SubElement(product_or_item_description, "ProductDescription").text = description

            if line.lot_id and line.lot_id.expiration_date:
                expiry_date = ET.SubElement(item_level, "Dates")
                ET.SubElement(expiry_date, "DateTimeQualifier").text = '036'
                ET.SubElement(expiry_date, "Date").text = datetime.strftime(line.lot_id.expiration_date.astimezone(pytz.timezone(tz)), EDI_DATE_FORMAT) or ''

            if line.lot_id:
                references = ET.SubElement(item_level, "References")
                ET.SubElement(references, "ReferenceQual").text = 'LT'
                ET.SubElement(references, "ReferenceID").text = str(line.lot_id.name) or ''

            line_count = line_count + 1

        return line_item, line_count



    def make_picking_xml_data(self, picking):
        tz = self.env.user.tz or pytz.utc
        picking_root = ET.Element("Shipment", xmlns='http://www.spscommerce.com/RSX')
        header = ET.SubElement(picking_root, "Header")

        # SHIPMENT HEADER
        shipment_header = ET.SubElement(header, "ShipmentHeader")
        source_so = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
        partner = source_so.partner_id or picking.partner_id or ''
        ET.SubElement(shipment_header, "TradingPartnerId").text = partner.trading_partnerid or ''
        ET.SubElement(shipment_header, "ShipmentIdentification").text = 'ASN_' + (source_so.x_po_number if source_so.x_po_number else picking.name)

        ET.SubElement(shipment_header, "ShipDate").text = datetime.strftime(picking.scheduled_date.astimezone(pytz.timezone(tz)), EDI_DATE_FORMAT) if picking.scheduled_date else datetime.strftime(fields.Datetime.now(), EDI_DATE_FORMAT)
        ET.SubElement(shipment_header, "ShipmentTime").text = datetime.strftime(source_so.effective_date, '%H:%M:%S') if source_so.effective_date else ''

        ET.SubElement(shipment_header, "TsetPurposeCode").text = source_so.x_tset_purpose_code or ''
        ET.SubElement(shipment_header, "ShipNoticeDate").text = datetime.strftime(picking.create_date, EDI_DATE_FORMAT) or ''
        ET.SubElement(shipment_header, "ShipNoticeTime").text = datetime.strftime(picking.create_date, '%H:%M:%S') or ''
        ET.SubElement(shipment_header, "ASNStructureCode").text = picking.x_asn_structure_code or '0001'
        ET.SubElement(shipment_header, "CarrierRouting").text = picking.x_carrier_routing or ''
        ET.SubElement(shipment_header, "BillOfLadingNumber").text = picking.x_bill_of_lading_number or ''
        ET.SubElement(shipment_header, "CarrierProNumber").text = picking.x_bill_of_lading_number or ''
        ET.SubElement(shipment_header, "CurrentScheduledDeliveryDate").text = datetime.strftime(picking.sale_id.commitment_date.astimezone(pytz.timezone(tz)), EDI_DATE_FORMAT) if picking.sale_id.commitment_date else ''
        ET.SubElement(shipment_header, "CurrentScheduledDeliveryTime").text = datetime.strftime(picking.sale_id.commitment_date.astimezone(pytz.timezone(tz)), '%H:%M:%S') if picking.sale_id.commitment_date else ''

        # payment_terms = ET.SubElement(header, "PaymentTerms")
        # dates = ET.SubElement(header, "Dates")

        # CONTACTS
        contacts_field = source_so.x_all_contacts
        contact_name = contacts_field.split('Name: ')[1].split('\n')[0] if contacts_field and 'Name: ' in contacts_field else ''
        contact_phone = contacts_field.split('Phone: ')[1].split('\n')[0] if contacts_field and 'Phone: ' in contacts_field else ''

        contacts = ET.SubElement(header, "Contacts")
        ET.SubElement(contacts, "ContactTypeCode").text = partner.x_contact_type_code or 'DI'
        ET.SubElement(contacts, "ContactName").text = picking.x_contact_name or contact_name or ''
        ET.SubElement(contacts, "PrimaryPhone").text = picking.x_contact_phone or contact_phone or ''

        # Write Ship From Address in header. Ship to Addresses go later

        # Address of the location where the order is being shipped FROM
        address = ET.SubElement(header, 'Address')
        ET.SubElement(address, 'AddressTypeCode').text = 'SF'
        ET.SubElement(address, 'LocationCodeQualifier').text = picking.company_id.partner_id.x_location_code_qualifier or '9'
        ET.SubElement(address, 'AddressLocationNumber').text = str(picking.company_id.partner_id.x_address_location_number) or ''
        ET.SubElement(address, 'AddressName').text = picking.company_id.name or ''
        ET.SubElement(address, 'Address1').text = picking.company_id.street or ''
        ET.SubElement(address, 'Address2').text = picking.company_id.street2 or ''
        ET.SubElement(address, 'City').text = picking.company_id.city or ''
        ET.SubElement(address, 'State').text = picking.company_id.state_id.code or ''
        ET.SubElement(address, 'PostalCode').text = picking.company_id.zip or ''
        ET.SubElement(address, 'Country').text = picking.company_id.country_id.code or ''

        address = ET.SubElement(header, "Address")
        ET.SubElement(address, "AddressTypeCode").text = 'ST'
        ET.SubElement(address, "LocationCodeQualifier").text = picking.partner_id.x_location_code_qualifier or '9'
        ET.SubElement(address, "AddressLocationNumber").text = str(picking.partner_id.x_address_location_number) or ''
        ET.SubElement(address, "AddressName").text = picking.partner_id.name or ''
        ET.SubElement(address, "Address1").text = picking.partner_id.street or ''
        ET.SubElement(address, "Address2").text = picking.partner_id.street2 or ''
        ET.SubElement(address, "City").text = picking.partner_id.city or ''
        ET.SubElement(address, "State").text = picking.partner_id.state_id.code or ''
        ET.SubElement(address, "PostalCode").text = picking.partner_id.zip or ''
        ET.SubElement(address, "Country").text = picking.partner_id.country_id.code or ''

        carrier_information = ET.SubElement(header, "CarrierInformation")
        ET.SubElement(carrier_information, "CarrierTransMethodCode").text = 'P'  # picking.x_carrier_trans_method_code
        ET.SubElement(carrier_information, "CarrierAlphaCode").text = picking.x_carrier_alpha_code or ''
        ET.SubElement(carrier_information, "CarrierRouting").text = picking.x_carrier_routing or ''

        quantity_and_weight = ET.SubElement(header, "QuantityAndWeight")
        ET.SubElement(quantity_and_weight, "LadingQuantity").text = str(len(picking.package_ids)) or '1'
        ET.SubElement(quantity_and_weight, "Weight").text = str(picking.x_weight) or '1'
        ET.SubElement(quantity_and_weight, "WeightUOM").text = picking.weight_uom_name.upper() or 'KG'
        if picking.move_line_ids_without_package and picking.move_line_ids_without_package[0].x_edi_uom.x_edi_code == 'CA':
            qty_field = 'move_line_ids_without_package.x_done_cases'
        else:
            qty_field = 'move_line_ids_without_package.qty_done'
        ET.SubElement(quantity_and_weight, "Quantity").text = str(sum(picking.mapped(qty_field))) or '0'
        ET.SubElement(quantity_and_weight, "QuantityTotalsQualifier").text = 'SQT'

        # quantity_totals = ET.SubElement(header, "QuantityTotals")
        # ET.SubElement(quantity_totals, "QuantityTotalsQualifier").text = picking.quantity_totals_qualifier
        # ET.SubElement(quantity_totals, "Quantity").text = picking.quantity_totals_qualifier
        # ET.SubElement(quantity_totals, "QuantityUOM").text = picking.quantity_totals_qualifier
        # ET.SubElement(quantity_totals, "Weight").text = picking.quantity_totals_qualifier
        # ET.SubElement(quantity_totals, "WeightUOM").text = picking.quantity_totals_qualifier

        inv_lines_tree, line_count = self.make_picking_line_xml_data(picking, source_so)
        picking_root.append(inv_lines_tree)

        summary = ET.SubElement(picking_root, "Summary")
        ET.SubElement(summary, "TotalLineItemNumber").text = str(line_count)

        return picking_root

    @api.model
    def _do_export_shipping_xml(self, conn, sync_action_id, values):
        '''
        Performs the document synchronization for the new document code
        @param conn : sftp/ftp connection class.
        @param sync_action_id: recordset of type `edi.sync.action`
        @param values:dict of values that may be useful to various methods
        @return bool : return bool (True|False)
        '''
        conn._connect()
        conn.cd(sync_action_id.dir_path)

        # Get shipments to be sent to edi:
        # Get individual records passed when SO hits button_validate()
        # or get all pending records when user runs the synchronization action manually
        pickings = values.get('records') or self.env['stock.picking'].sudo().search([('x_edi_status', '=', 'pending'), ('state', '=', 'done')])

        for picking in pickings:
            picking_data = self.make_picking_xml_data(picking)
            picking_data = ET.ElementTree(picking_data)

            if picking_data:
                filename = '856_shipment_%s.xml' % picking.name.replace('/', '_')
                with open(filename, 'wb') as file:
                    picking_data.write(file, pretty_print=True)

                filename = filename.strip()
                try:
                    with open(filename, 'rb') as file:
                        conn.upload_file(filename, file)
                        file.close()
                    # Update EDI Status to sent
                    picking.write({'x_edi_status': 'sent', 'x_edi_date': fields.Datetime.now()})
                    picking.sudo().message_post(body=_('Shipping file created on the EDI server %s' % filename))
                    _logger.info('Shipping file created on the server path of %s/%s' % (sync_action_id.dir_path, filename))
                except Exception as e:
                    picking.write({'x_edi_status': 'fail'})
                    _logger.error("file not uploaded %s" % e)
                os.remove(filename)
            self.flush()
        conn._disconnect()
        return True