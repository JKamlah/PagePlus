from lxml import etree as ET

NS2013 = 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15'
NS2019 = 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15'
NS = {'p2013': NS2013, 'p2019': NS2019}


class TranskribusToPrima():
    """
    Translates Transkribus variant of PAGE to standard-conformant PAGE
    """

    def __init__(self, tree, prefer_imgurl=False):
        self.tree = tree
        self.prefer_imgurl = prefer_imgurl

    def convert_metadata(self):
        """Remove any Metadata/TranskribusMetadata"""
        el_page = self.tree.find('{*}Page')
        el_metadata = self.tree.find('{*}Metadata')
        if el_metadata is not None:
            el_metadata = el_metadata.find('{*}TranskribusMetadata')
        if el_metadata is not None:
            if self.prefer_imgurl and 'imgUrl' in el_metadata.attrib:
                el_page.attrib['imageFilename'] = el_metadata.attrib['imgUrl']
            el_metadata.getparent().remove(el_metadata)

    def convert_reading_order(self):
        """Convert reading order from Relations (Transkribus) to ReadingOrder (PRImA)"""
        ro_with_oo = self.tree.xpath(
            '//*[local-name()="ReadingOrder"]/*[local-name()="OrderedGroup"]')
        if not len(ro_with_oo):
            return
        ro = ro_with_oo[0]
        relations = self.tree.xpath('//*[local-name()="Relations"]')
        if not len(relations):
            return
        relations = relations[0]
        for relation in relations.xpath('*[local-name()="Relation"][@type="link"]'):
            region_refs = relation.xpath('*[local-name()="RegionRef"]')
            ro_grp = ET.SubElement(ro, 'OrderedGroupIndexed')
            ro_grp.set('id', 'relation_link_' +
                       '-'.join([x.get('regionRef') for x in region_refs]))
            ro_grp.set('index', str(
                int(ro.xpath('*[local-name()="RegionRefIndexed"]')[-1].get('index')) + 1))
            for idx, region_ref in enumerate(region_refs):
                ro_region_ref = ET.SubElement(ro_grp, 'RegionRefIndexed')
                ro_region_ref.set('regionRef', region_ref.get('regionRef'))
                ro_region_ref.set('index', str(idx))
            relation.getparent().remove(relation)
        if not relations.findall('*'):
            relations.getparent().remove(relations)

    def convert_table(self):
        """Convert each TableRegion/TableCell into a TableRegion/TextRegion, writing row/col index/span as new TableCellRole accordingly"""
        for el_table in self.tree.xpath('//*[local-name()="TableRegion"]'):
            for el_cell in el_table.xpath('*[local-name()="TableCell"]'):
                el_table.remove(el_cell)
                el_region = ET.SubElement(el_table, '{%s}TextRegion' % NS2013)
                for att in ['id', 'custom', 'comments', 'continuation', 'production',
                            'orientation', 'type', 'leading', 'indented', 'align',
                            'readingDirection', 'readingOrientation', 'textLineOrder',
                            'primaryLanguage', ',secondaryLanguage',
                            'primaryScript', 'secondaryScript']:
                    if att in el_cell.attrib:
                        el_region.set(att, el_cell.get(att))
                for node in el_cell.iterchildren("{*}AlternativeImage", "{*}Coords",
                                                 "{*}UserDefined", "{*}Labels",
                                                 "{*}Roles"):
                    el_region.append(node)
                el_roles = el_region.find('{*}Roles')
                if el_roles is None:
                    el_roles = ET.SubElement(el_region, '{%s}Roles' % NS2013)
                # NS2013 does not have TableCellRole, so we implicitly rely on the namespace converter here
                el_tablecellrole = ET.SubElement(
                    el_roles, '{%s}TableCellRole' % NS2013)
                el_tablecellrole.set('rowIndex', el_cell.get('row'))
                el_tablecellrole.set('columnIndex', el_cell.get('col'))
                el_tablecellrole.set('rowSpan', el_cell.get('rowSpan', '1'))
                el_tablecellrole.set('colSpan', el_cell.get('colSpan', '1'))
                el_tablecellrole.set('header', el_cell.get('label', "false"))
                for node in el_cell.iterchildren():
                    if any(node.tag.endswith(suf)
                           for suf in ['Region', 'TextLine', 'TextEquiv', 'TextStyle']):
                        el_region.append(node)

    def convert_textequiv(self):
        """Convert any //TextEquiv/UnicodeAlternative into additional ../TextEquiv/Unicode"""
        for el_te in self.tree.xpath('//*[local-name()="TextEquiv"]'):
            for el_uni in el_te.xpath('//*[local-name()="UnicodeAlternative"]'):
                el_te.remove(el_uni)
                el_tenew = ET.SubElement(
                    el_te.getparent(), '{%s}TextEquiv' % NS2013)
                el_tenewuni = ET.SubElement(el_tenew, '{%s}Unicode' % NS2013)
                el_tenewuni.text = el_uni.text

    def convert_image_transform(self):
        """Convert Page/@image(Rotation|Translation|Scaling) to Labels"""
        el_page = self.tree.find('{*}Page')
        el_labels = el_page.find('{*}Labels')

        def new_label(typ, val):
            nonlocal el_labels
            if el_labels is None:
                el_labels = ET.Element('{%s}Labels' % NS2013)
                el_labels.set('externalModel', 'TranskribusImageTransform')
                # find position to insert (labels go right before regions)
                regions = el_page.xpath('*[contains(local-name(),"Region")]')
                if len(regions):
                    regions[0].addprevious(el_labels)
                else:
                    el_page.append(el_labels)
            el_label = ET.SubElement(el_labels, '{%s}Label' % NS2013)
            el_label.set('type', typ)
            el_label.set('value', val)
        for label in ['imageRotation',
                      'imageTranslationX',
                      'imageTranslationY',
                      'imageScalingX',
                      'imageScalingY']:
            if label in el_page.attrib:
                new_label(label, el_page.attrib.pop(label))

    def convert_tag_property_link(self):
        """Remove Tag, Property and Link elements whereever they appear"""
        # all known under PageType, RegionType, TextLineType, WordType, GlyphType
        # Tag known under TextEquivType
        # Property known under TranskribusMetadataType
        # ...but we might as well search everywhere
        # FIXME: convert these to Labels and Relations
        for node in self.tree.iter():
            tag = node.find('{*}Tag')
            if tag is not None:
                node.remove(tag)
            prop = node.find('{*}Property')
            if prop is not None:
                node.remove(prop)
            link = node.find('{*}Link')
            if link is not None:
                node.remove(link)

    def tostring(self):
        return ET.tostring(self.tree,
                           pretty_print=True,
                           xml_declaration=True,
                           encoding='utf-8').decode('utf-8')
