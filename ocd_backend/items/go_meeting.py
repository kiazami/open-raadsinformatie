from datetime import datetime
import json
from pprint import pprint
from hashlib import sha1
from time import sleep
import re
import urlparse

from lxml import etree
import iso8601

from ocd_backend.items.popolo import EventItem
from ocd_backend.utils.misc import slugify
from ocd_backend import settings
from ocd_backend.extractors import HttpRequestMixin
from ocd_backend.utils.api import FrontendAPIMixin
from ocd_backend.utils.pdf import PDFToTextMixin


class MeetingItem(
        EventItem, HttpRequestMixin, FrontendAPIMixin, PDFToTextMixin):

    @property
    def html(self):
        _old_html = getattr(self, '_html', None)

        if _old_html is not None:
            return _old_html

        self._html = etree.HTML(self.original_item['content'])
        return self._html

    @property
    def full_html(self):
        _old_html = getattr(self, '_full_html', None)

        if _old_html is not None:
            return _old_html

        self._full_html = etree.HTML(self.original_item['full_content'])
        return self._full_html

    def _get_council(self):
        """
        Gets the organisation that represents the council.
        """

        results = self.api_request(
            self.source_definition['index_name'], 'organizations',
            classification='council')
        return results[0]

    def _find_meeting_type_id(self, org):
        results = [x for x in org['identifiers'] if x['scheme'] == u'GemeenteOplossingen']
        return results[0]['identifier']

    def _get_committees(self):
        """
        Gets the committees that are active for the council.
        """

        results = self.api_request(
            self.source_definition['index_name'], 'organizations',
            classification=['committee', 'subcommittee'])
        return {self._find_meeting_type_id(c): c for c in results}

    def _convert_date(self, date_str):
        month_names2int = {
            u'januari': u'01',
            u'februari': u'02',
            u'maart': u'03',
            u'april': u'04',
            u'mei': u'05',
            u'juni': u'06',
            u'juli': u'07',
            u'augustus': u'08',
            u'september': u'09',
            u'oktober': u'10',
            u'november': u'11',
            u'december': u'12',
        }
        output = date_str
        for k, v in month_names2int.iteritems():
            output = output.replace(k, v)
        parts = output.split(u' ')
        return u'%s-%s-%s' % (parts[2], parts[1], parts[0],)

    def _get_object_id_for(self, object_id, urls={}):
        """Generates a new object ID which is used within OCD to identify
        the item.

        By default, we use a hash containing the id of the source, the
        original object id of the item (:meth:`~.get_original_object_id`)
        and the original urls (:meth:`~.get_original_object_urls`).

        :raises UnableToGenerateObjectId: when both the original object
            id and urls are missing.
        :rtype: str
        """

        if not object_id and not urls:
            raise UnableToGenerateObjectId('Both original id and urls missing')

        hash_content = self.source_definition['id'] + object_id #+ u''.join(sorted(urls.values()))

        return sha1(hash_content.decode('utf8')).hexdigest()

    def _get_meeting_item_id(self):
        return self.html.xpath('.//@id')[0].replace(u'agendapunt', '').split(u'_')[0]

    def _get_meeting_item_documents_url(self):
        return u'%s/modules/risbis/risbis.php?g=get_docs_for_ag&agendapunt_object_id=%s' % (
            self.source_definition['base_url'], self._get_meeting_item_id(),)

    def _get_documents_html_for_item(self):
        url = self._get_meeting_item_documents_url()

        resp = self.http_session.get(url)
        if resp.status_code == 200:
            return resp.content

        return u''

    def _get_current_permalink(self, include_hash=True):
        """
        GemeenteOplossing has instable perma links -- The URLs change when
        the time of the meeting is changed. This accounts for it and returns
        a the current permalink that is used externally.
        """

        permalink = u''.join(
            self.full_html.xpath('//meta[@property="og:url"]/@content')).strip()
        if self.original_item['type'] == 'meeting':
            return permalink
        else:
            if include_hash:
                return u'%s#%s' % (permalink, self.html.xpath('.//@id')[0],)
            else:
                return permalink

    def _get_stable_permalink(self, include_hash=True):
        """
        GemeenteOplossing has instable perma links -- The URLs change when
        the time of the meeting is changed. This accounts for it and returns
        a stable permalink that is used internally.
        """

        permalink = self._get_current_permalink(include_hash)
        return re.sub(r'/\d{2}:\d{2}/', u'/00:00/', permalink)

    def get_object_id(self):
        hash_content = self.source_definition['id'] + self.get_original_object_id()
        return sha1(hash_content.decode('utf8')).hexdigest()

    def get_original_object_id(self):
        return self._get_stable_permalink()

    def get_original_object_urls(self):
        # FIXME: what to do when there is not an original URL?
        return {"html": self._get_current_permalink()}

    def get_rights(self):
        return u'undefined'

    def get_collection(self):
        return unicode(self.source_definition['index_name'])

    def get_combined_index_data(self):
        combined_index_data = {}

        council = self._get_council()
        committees = self._get_committees()

        combined_index_data['id'] = unicode(self.get_object_id())

        combined_index_data['hidden'] = self.source_definition['hidden']

        if self.original_item['type'] == 'meeting':
            combined_index_data['name'] = u''.join(
                self.full_html.xpath('//title/text()')).strip()
            combined_index_data['classification'] = u'Meeting'
        else:
            meeting_item_index = (
                u''.join(self.html.xpath('.//div[@class="first"]//text()')).strip())
            combined_index_data['name'] = u'%s. %s' % (
                meeting_item_index,
                u''.join(self.html.xpath('.//div[@class="title"]/h3//text()')).strip(),
            )
            combined_index_data['classification'] = u'Meeting Item'

        combined_index_data['identifiers'] = [
            {
                'identifier': unicode(self._get_current_permalink()),
                'scheme': u'GemeenteOplossingen'
            },
            {
                'identifier': self.get_object_id(),
                'scheme': u'ORI'
            }
        ]

        organisation_name = u''.join(
            self.full_html.xpath('//h2[@class="page_title"]/span//text()'))
        try:
            combined_index_data['organization_id'] = committees[
                organisation_name]['id']
            combined_index_data['organization'] = committees[
                organisation_name]
        except KeyError as e:
            combined_index_data['organization_id'] = council['id']
            combined_index_data['organization'] = council


        if self.original_item['type'] != 'meeting':
            combined_index_data['description'] = u''.join(self.html.xpath('.//div[@class="toelichting"]//text()'),)
        else:
            combined_index_data['description'] = u''


        meeting_date = u''.join(
             self.full_html.xpath('//span[@class="date"]//text()')).strip()
        meeting_time = u''.join(
             self.full_html.xpath('//span[@class="time"]//text()')).strip()

        combined_index_data['start_date'] = iso8601.parse_date(u'%sT%s:00Z' % (
            self._convert_date(meeting_date), meeting_time,))
        combined_index_data['end_date'] = combined_index_data['start_date']

        combined_index_data['location'] = u'Gemeentehuis'
        combined_index_data['status'] = u'confirmed'
        combined_index_data['sources'] = [
            {
                'url': self._get_current_permalink(),
                'note': u''
            }
        ]

        if self.original_item['type'] != 'meeting':
            parent_url = self._get_stable_permalink(False)
            pprint(parent_url)
            combined_index_data['parent_id'] = unicode(self._get_object_id_for(
                parent_url, {"html": parent_url}))

            # FIXME: in order to get the documents for an meeting item you
            # need to do a separate request:
            # https://gemeenteraad.denhelder.nl/modules/risbis/risbis.php?g=get_docs_for_ag&agendapunt_object_id=19110

            if (len(self.html.xpath('.//a[contains(@class, "bijlage_true")]')) > 0):
                docs_contents = self._get_documents_html_for_item()
                if docs_contents:
                    docs_html = etree.HTML(docs_contents)
                else:
                    docs_html = etree.HTML('<ul></ul>')

                for doc in docs_html.xpath('//li/a'):
                    doc_url = u''.join(doc.xpath('.//@href')).strip()
                    if not doc_url.startswith('http'):
                        doc_url = u'%s%s' % (self.source_definition['base_url'], doc_url,)
                    doc_note = u''.join(doc.xpath('.//text()')).strip()
                    if doc_note != u'notitie':
                        combined_index_data['sources'].append({
                            'url': doc_url,
                            'note': doc_note
                        })
        else:
            combined_index_data['children'] = [
                unicode(self._get_object_id_for(
                    i, {"html": i}
                )) for i in self.full_html.xpath(
                    '//li[contains(@class, "agendaRow")]/div[@class="first"]/a/@href'
            )]

            base_url = u''.join(
                self.full_html.xpath('//meta[@property="og:url"]/@content')).strip()

            for doc in self.full_html.xpath('//div[@id="documenten"]//li/a'):
                doc_url = urlparse.urljoin(
                    base_url, u''.join(doc.xpath('.//@href')).strip())
                doc_note = u''.join(doc.xpath('.//text()')).strip()
                if doc_note != u'notitie':
                    combined_index_data['sources'].append({
                        'url': doc_url,
                        'note': doc_note
                    })

            for doc in self.full_html.xpath('//div[@id="downloaden"]/ul//li/a'):
                doc_url = urlparse.urljoin(
                    base_url, u''.join(doc.xpath('.//@href')).strip())
                doc_note = u''.join(doc.xpath('.//text()')).strip()
                if doc_note != u'notitie':
                    combined_index_data['sources'].append({
                        'url': doc_url,
                        'note': doc_note
                    })

        for source in combined_index_data['sources']:
            if not source['url'].lower().endswith('.pdf'):
                continue
            source['description'] = self.pdf_get_contents(
                source['url'], self.source_definition.get('pdf_max_pages', 20))

        return combined_index_data

    def get_index_data(self):
        return {}

    def get_all_text(self):
        text_items = []

        return u' '.join(text_items)
