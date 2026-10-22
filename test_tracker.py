import unittest
import xml.etree.ElementTree as ET
from tracker import crawl, merge, folder_id

class TrackerTests(unittest.TestCase):
    def test_recursive_pagination_and_dedup(self):
        calls = []
        def fetch(ident, offset, limit):
            calls.append((ident, offset))
            if ident == 'root' and offset == 0:
                xml = '<total>3</total><folder><ident>sub</ident><name>Sub</name></folder><file><ident>a</ident><name>A</name></file>'
            elif ident == 'root':
                xml = '<total>3</total><file><ident>b</ident><name>B</name></file>'
            else:
                xml = '<total>1</total><file><ident>a</ident><name>A</name></file>'
            return ET.fromstring('<response><name>Root</name>' + xml + '</response>')
        found = crawl('root', fetch)
        self.assertEqual(set(found), {'a', 'b'})
        self.assertIn(('root', 2), calls)
        self.assertEqual(len(found['a']['folders']), 2)

    def test_preserve_status_and_missing(self):
        old = {'a': {'status': 'hotovo', 'note': 'OK', 'first_seen': 'before'}, 'b': {'status': 'nové'}}
        result = merge(old, {'a': {'name': 'renamed'}}, 'now')
        self.assertEqual(result['a']['status'], 'hotovo')
        self.assertEqual(result['a']['note'], 'OK')
        self.assertEqual(result['a']['first_seen'], 'before')
        self.assertNotIn('b', result)

    def test_repeated_page_fails(self):
        def fetch(*args):
            return ET.fromstring('<response><total>10</total><file><ident>a</ident></file></response>')
        with self.assertRaises(ValueError):
            crawl('root', fetch)

    def test_input(self):
        self.assertEqual(folder_id('https://webshare.cz/#/folder/QFWv3mjitp/x'), 'QFWv3mjitp')
        with self.assertRaises(ValueError):
            folder_id('https://example.com')

if __name__ == '__main__':
    unittest.main()

class DownloadTests(unittest.TestCase):
    def test_error_classification(self):
        from tracker import check_download
        expected = {'1': 'nenalezen', '3': 'vyžaduje_heslo', '4': 'dočasně_nedostupný', '5': 'limit_stahování', '6': 'neveřejný', '99': 'neověřeno'}
        for suffix, status in expected.items():
            def request(ident):
                return ET.fromstring(f'<response><status>FATAL</status><code>FILE_LINK_FATAL_{suffix}</code><message>Error</message></response>')
            self.assertEqual(check_download('a', request)['download_status'], status)

    def test_link_not_persisted(self):
        from tracker import check_download
        result = check_download('a', lambda _: ET.fromstring('<response><status>OK</status><link>https://secret-download.example/token</link></response>'))
        self.assertEqual(result['download_status'], 'odkaz_vydán')
        self.assertNotIn('secret-download', str(result))

    def test_network_error_is_not_unavailable(self):
        from tracker import check_download
        def request(_):
            raise OSError('secret')
        result = check_download('a', request)
        self.assertEqual(result['download_status'], 'chyba_kontroly')
        self.assertNotIn('secret', str(result))

    def test_scan_preserves_check_and_manual_status(self):
        from tracker import merge
        old = {'a': {'status': 'hotovo', 'note': 'OK', 'download_status': 'dočasně_nedostupný', 'checked_at': 'yesterday'}}
        new = merge(old, {'a': {'name': 'A'}}, 'today')['a']
        self.assertNotIn('download_status', new)
        self.assertNotIn('checked_at', new)
        self.assertEqual(new['status'], 'hotovo')

class ReadmeTests(unittest.TestCase):
    def test_readme_counts_and_escaping(self):
        from tracker import render_summary
        data = {'files': {'a': dict(id='a', name='A|<x>[test]', url='https://webshare.cz/#/file/a', present=True, status='hotovo', note='one\ntwo', download_status='dočasně_nedostupný'), 'b': dict(id='b', name='B', url='https://webshare.cz/#/file/b', present=False)}}
        result = render_summary(data)
        self.assertIn('1 souborů ve složce', result)
        self.assertIn('| dočasně_nedostupný | 1 |', result)
        self.assertIn('A&#124;&lt;x&gt;&#91;test&#93;', result)
        self.assertIn('one two', result)

    def test_readme_update_idempotent_replaces_old_content(self):
        import tempfile
        from pathlib import Path
        from tracker import update_readme, README_START
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root/'README.md').write_text('# Vlastní návod\n', encoding='utf-8')
            update_readme({'files': {}}, root/'data')
            update_readme({'files': {}}, root/'data')
            result = (root/'README.md').read_text()
            self.assertEqual(result.count(README_START), 1)
            self.assertNotIn('# Vlastní návod', result)

class RefreshTests(unittest.TestCase):
    def test_fresh_inventory_drives_links_and_checks(self):
        from tracker import merge, check_records, export
        from pathlib import Path
        import tempfile
        old = {'removed': dict(id='removed', name='Old', url='https://webshare.cz/#/file/removed', folders=[], size_bytes='1', status='hotovo', note='Keep', first_seen='old', last_seen='old', present=True)}
        found = {'new': dict(id='new', name='New', url='https://webshare.cz/#/file/new', folders=['Root'], size_bytes='1')}
        data = {'files': merge(old, found, 'now')}
        calls = []
        def request(ident):
            calls.append(ident)
            return ET.fromstring('<response><status>FATAL</status><code>FILE_LINK_FATAL_4</code></response>')
        check_records(data, request=request, delay=0)
        self.assertEqual(calls, ['new'])
        self.assertNotIn('removed', data['files'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            out = Path(tmp)/'data'
            export(data, out)
            self.assertEqual((out/'links.txt').read_text(), 'https://webshare.cz/#/file/new\n')

    def test_workflow_refresh_precedes_check_and_status(self):
        from pathlib import Path
        workflow = (Path(__file__).parent/'.github/workflows/inventory.yml').read_text()
        scan = workflow.index('run: python -u tracker.py scan')
        check = workflow.index('run: python -u tracker.py check')
        status = workflow.index('python tracker.py status')
        self.assertLess(scan, check)
        self.assertLess(check, status)


class CurrentSnapshotTests(unittest.TestCase):
    def test_removed_links_absent_from_readme_and_csv(self):
        from tracker import export
        from pathlib import Path
        import tempfile
        records = {}
        for fid, present in [('CURRENT', True), ('HISTORICAL', False)]:
            records[fid] = dict(id=fid, name=fid, url='https://webshare.cz/#/file/' + fid, present=present, folders=[], size_bytes='1', status='nové', note='', first_seen='old', last_seen='now')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root/'README.md').write_text('Old stale links outside markers')
            export({'files': records}, root/'data')
            for path in [root/'README.md', root/'data/inventory.csv', root/'data/links.txt']:
                text = path.read_text()
                self.assertIn('CURRENT', text)
                self.assertNotIn('HISTORICAL', text)
                self.assertNotIn('Old stale links', text)
            self.assertIn('HISTORICAL', (root/'data/inventory.json').read_text())
