import re
import tempfile
import unittest
from pathlib import Path

from nfc import Plate, create_app, db


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = dict(TESTING=True, SECRET_KEY='s' * 40,
                           ADMIN_PASSWORD='a-long-test-password', SESSION_COOKIE_SECURE=False,
                           SQLALCHEMY_DATABASE_URI='sqlite:///' + (Path(self.directory.name) / 'test.db').as_posix())
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.directory.cleanup()

    def token(self, path='/admin/login'):
        response = self.client.get(path)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def login(self):
        return self.client.post('/admin/login', data={
            'csrf_token': self.token(), 'password': self.config['ADMIN_PASSWORD']})

    def test_public_routes(self):
        self.assertEqual(self.client.get('/').location, '/r/001')
        page = self.client.get('/r/001')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Демо-компания', page.text)
        self.assertIn('https://yandex.ru/maps/', page.text)
        self.assertIn('https://2gis.ru/', page.text)
        self.assertEqual(self.client.get('/health').json, {'ok': True})
        self.assertEqual(self.client.get('/admin/login').status_code, 200)
        self.assertEqual(self.client.get('/r/missing').status_code, 404)
        self.assertEqual(self.client.get('/admin').location, '/admin/login')

    def test_crud_and_isolation(self):
        self.assertEqual(self.login().status_code, 302)
        data = dict(id='002', business_name='Кофейня', yandex_url='https://yandex.ru/maps/123',
                    two_gis_url='', active='on', csrf_token=self.token('/admin/new'))
        self.assertEqual(self.client.post('/admin/new', data=data).status_code, 302)
        page = self.client.get('/r/002').text
        self.assertIn('https://yandex.ru/maps/123', page)
        self.assertIn('Ссылка пока не добавлена', page)
        self.assertNotIn('Кофейня', self.client.get('/r/001').text)
        self.assertEqual(self.client.post('/admin/new', data=data).status_code, 400)
        data['business_name'] = 'Новое название'
        data['csrf_token'] = self.token('/admin/002/edit')
        self.assertEqual(self.client.post('/admin/002/edit', data=data).status_code, 302)
        self.assertIn('Новое название', self.client.get('/r/002').text)
        token = self.token('/admin')
        self.assertEqual(self.client.post('/admin/002/toggle', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.client.get('/r/002').status_code, 404)
        self.client.post('/admin/002/toggle', data={'csrf_token': token})
        self.assertEqual(self.client.get('/r/002').status_code, 200)
        self.assertEqual(self.client.get('/admin/002/delete').status_code, 200)
        self.assertEqual(self.client.get('/r/002').status_code, 200)
        self.client.post('/admin/002/delete', data={'csrf_token': token})
        self.assertEqual(self.client.get('/r/002').status_code, 404)
        self.client.post('/admin/logout', data={'csrf_token': token})
        self.assertEqual(self.client.get('/admin').location, '/admin/login')

    def test_security_and_validation(self):
        self.assertEqual(self.client.post('/admin/login', data={'password': 'bad'}).status_code, 400)
        self.assertEqual(self.client.post('/admin/001/delete').status_code, 400)
        self.login()
        token = self.token('/admin/new')
        for url in ['javascript:alert(1)', '//evil.com', 'https://user:pass@evil.com', 'https://host.com:bad', 'https://evil.com\\x']:
            response = self.client.post('/admin/new', data=dict(
                id='003', business_name='Test', yandex_url=url, csrf_token=token))
            self.assertEqual(response.status_code, 400, url)
        self.assertEqual(self.client.get('/r/003').status_code, 404)
        response = self.client.post('/admin/new', data=dict(
            id='004', business_name='<script>alert(1)</script>', active='on', csrf_token=token))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('<script>', self.client.get('/r/004').text)
        self.assertEqual(self.client.get('/admin').headers['Cache-Control'], 'no-store')

    def test_login_limit(self):
        token = self.token()
        for _ in range(10):
            self.assertEqual(self.client.post('/admin/login', data={'csrf_token': token, 'password': 'bad'}).status_code, 401)
        self.assertEqual(self.client.post('/admin/login', data={'csrf_token': token, 'password': 'bad'}).status_code, 429)

    def test_demo_not_recreated(self):
        self.login()
        self.client.post('/admin/001/delete', data={'csrf_token': self.token('/admin')})
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.app = create_app(self.config)
        self.assertEqual(self.app.test_client().get('/r/001').status_code, 404)

    def test_rename_and_duplicate_preserves_data(self):
        self.login()
        token = self.token('/admin/new')
        self.client.post('/admin/new', data=dict(id='002', business_name='Second', active='on', csrf_token=token))
        response = self.client.post('/admin/002/edit', data=dict(id='001', business_name='Collision', active='on', csrf_token=token))
        self.assertEqual(response.status_code, 400)
        self.assertIn('Second', self.client.get('/r/002').text)
        self.client.post('/admin/002/edit', data=dict(id='003', business_name='Renamed', active='on', csrf_token=token))
        self.assertEqual(self.client.get('/r/002').status_code, 404)
        self.assertIn('Renamed', self.client.get('/r/003').text)

    def test_error_handler(self):
        self.app.config['TESTING'] = False
        @self.app.get('/test-error')
        def fail():
            raise RuntimeError('test failure')
        response = self.client.get('/test-error')
        self.assertEqual(response.status_code, 500)
        self.assertIn('Что-то пошло не так', response.text)
        self.assertNotIn('test failure', response.text)


if __name__ == '__main__':
    unittest.main()
