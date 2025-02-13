import sys
import unittest
import tarantool
from .lib.tarantool_server import TarantoolServer
from tarantool.error import NotSupportedError


# FIXME: I'm quite sure that there is a simpler way to count
# a method calls, but I failed to find any. It seems, I should
# look at unittest.mock more thoroughly.
class MethodCallCounter:
    def __init__(self, obj, method_name):
        self._call_count = 0
        self._bind(obj, method_name)

    def _bind(self, obj, method_name):
        self._obj = obj
        self._method_name = method_name
        self._saved_method = getattr(obj, method_name)
        def wrapper(_, *args, **kwargs):
            self._call_count += 1
            return self._saved_method(*args, **kwargs)
        bound_wrapper = wrapper.__get__(obj.__class__, obj)
        setattr(obj, method_name, bound_wrapper)

    def unbind(self):
        if self._saved_method is not None:
            setattr(self._obj, self._method_name, self._saved_method)

    def call_count(self):
        return self._call_count


class TestSuite_Schema_Abstract(unittest.TestCase):
    # Define 'encoding' field in a concrete class.

    @classmethod
    def setUpClass(self):
        params = 'connection.encoding: {}'.format(repr(self.encoding))
        print(' SCHEMA ({}) '.format(params).center(70, '='), file=sys.stderr)
        print('-' * 70, file=sys.stderr)
        self.srv = TarantoolServer()
        self.srv.script = 'test/suites/box.lua'
        self.srv.start()
        self.srv.admin("box.schema.user.create('test', {password = 'test', " +
              "if_not_exists = true})")
        self.srv.admin("box.schema.user.grant('test', 'read,write,execute', 'universe')")

        # Create server_function and tester space (for fetch_schema opt testing purposes).
        self.srv.admin("function server_function() return 2+2 end")
        self.srv.admin("""
        box.schema.create_space(
            'tester', {
            format = {
                {name = 'id', type = 'unsigned'},
                {name = 'name', type = 'string', is_nullable = true},
            }
        })
        """)
        self.srv.admin("""
        box.space.tester:create_index(
            'primary_index', {
            parts = {
                {field = 1, type = 'unsigned'},
            }
        })
        """)
        self.srv.admin("box.space.tester:insert({1, null})")

        self.con = tarantool.Connection(self.srv.host, self.srv.args['primary'],
                                        encoding=self.encoding, user='test', password='test')
        self.con_schema_disable = tarantool.Connection(self.srv.host, self.srv.args['primary'],
                                                       encoding=self.encoding, fetch_schema=False,
                                                       user='test', password='test')
        if not sys.platform.startswith("win"):
            # Schema fetch disable tests via mesh and pool connection
            # are not supported on windows platform.
            self.mesh_con_schema_disable = tarantool.MeshConnection(host=self.srv.host, 
                                                                    port=self.srv.args['primary'],
                                                                    fetch_schema=False, 
                                                                    user='test', password='test')
            self.pool_con_schema_disable = tarantool.ConnectionPool([{'host':self.srv.host, 
                                                                    'port':self.srv.args['primary']}], 
                                                                    user='test', password='test',
                                                                    fetch_schema=False)
        self.sch = self.con.schema

        # The relevant test cases mainly target Python 2, where
        # a user may want to pass a string literal as a space or
        # an index name and don't bother whether all symbols in it
        # are ASCII.
        self.unicode_space_name_literal = '∞'
        self.unicode_index_name_literal = '→'

        self.unicode_space_name_u = u'∞'
        self.unicode_index_name_u = u'→'
        self.unicode_space_id, self.unicode_index_id = self.srv.admin("""
            do
                local space = box.schema.create_space('\\xe2\\x88\\x9e')
                local index = space:create_index('\\xe2\\x86\\x92')
                return space.id, index.id
            end
        """)

    def setUp(self):
        # prevent a remote tarantool from clean our session
        if self.srv.is_started():
            self.srv.touch_lock()

        # Count calls of fetch methods. See <fetch_count>.
        self.fetch_space_counter = MethodCallCounter(self.sch, 'fetch_space')
        self.fetch_index_counter = MethodCallCounter(self.sch, 'fetch_index')

    def tearDown(self):
        self.fetch_space_counter.unbind()
        self.fetch_index_counter.unbind()

    @property
    def fetch_count(self):
        """Amount of fetch_{space,index}() calls.

           It is initialized to zero before each test case.
        """
        res = 0
        res += self.fetch_space_counter.call_count()
        res += self.fetch_index_counter.call_count()
        return res

    def verify_unicode_space(self, space):
        self.assertEqual(space.sid, self.unicode_space_id)
        self.assertEqual(space.name, self.unicode_space_name_u)
        self.assertEqual(space.arity, 1)

    def verify_unicode_index(self, index):
        self.assertEqual(index.space.name, self.unicode_space_name_u)
        self.assertEqual(index.iid, self.unicode_index_id)
        self.assertEqual(index.name, self.unicode_index_name_u)
        self.assertEqual(len(index.parts), 1)

    def test_01_space_bad(self):
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no space.*'):
            self.sch.get_space(0)
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no space.*'):
            self.sch.get_space(0)
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no space.*'):
            self.sch.get_space('bad_name')

    def test_02_index_bad(self):
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no space.*'):
            self.sch.get_index(0, 'primary')
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no space.*'):
            self.sch.get_index('bad_space', 'primary')
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no index.*'):
            self.sch.get_index(280, 'bad_index')
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no index.*'):
            self.sch.get_index(280, 'bad_index')
        with self.assertRaisesRegex(tarantool.SchemaError,
                'There\'s no index.*'):
            self.sch.get_index(280, 3)

    def test_03_01_space_name__(self):
        self.con.flush_schema()
        space = self.sch.get_space('_schema')
        self.assertEqual(space.sid, 272)
        self.assertEqual(space.name, '_schema')
        self.assertEqual(space.arity, 1)
        space = self.sch.get_space('_space')
        self.assertEqual(space.sid, 280)
        self.assertEqual(space.name, '_space')
        self.assertEqual(space.arity, 1)
        space = self.sch.get_space('_index')
        self.assertEqual(space.sid, 288)
        self.assertEqual(space.name, '_index')
        self.assertEqual(space.arity, 1)

        space = self.sch.get_space(self.unicode_space_name_literal)
        self.verify_unicode_space(space)

    def test_03_02_space_number(self):
        self.con.flush_schema()
        space = self.sch.get_space(272)
        self.assertEqual(space.sid, 272)
        self.assertEqual(space.name, '_schema')
        self.assertEqual(space.arity, 1)
        space = self.sch.get_space(280)
        self.assertEqual(space.sid, 280)
        self.assertEqual(space.name, '_space')
        self.assertEqual(space.arity, 1)
        space = self.sch.get_space(288)
        self.assertEqual(space.sid, 288)
        self.assertEqual(space.name, '_index')
        self.assertEqual(space.arity, 1)

        space = self.sch.get_space(self.unicode_space_id)
        self.verify_unicode_space(space)

    def test_04_space_cached(self):
        space = self.sch.get_space('_schema')
        self.assertEqual(space.sid, 272)
        self.assertEqual(space.name, '_schema')
        self.assertEqual(space.arity, 1)
        space = self.sch.get_space('_space')
        self.assertEqual(space.sid, 280)
        self.assertEqual(space.name, '_space')
        self.assertEqual(space.arity, 1)
        space = self.sch.get_space('_index')
        self.assertEqual(space.sid, 288)
        self.assertEqual(space.name, '_index')
        self.assertEqual(space.arity, 1)

        # Verify that no schema fetches occurs.
        self.assertEqual(self.fetch_count, 0)

        space = self.sch.get_space(self.unicode_space_name_literal)
        self.verify_unicode_space(space)

        # Verify that no schema fetches occurs.
        self.assertEqual(self.fetch_count, 0)

    def test_05_01_index_name___name__(self):
        self.con.flush_schema()
        index = self.sch.get_index('_index', 'primary')
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index('_index', 'name')
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index('_space', 'primary')
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 1)
        index = self.sch.get_index('_space', 'name')
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 1)

        index = self.sch.get_index(self.unicode_space_name_literal,
                                   self.unicode_index_name_literal)
        self.verify_unicode_index(index)

    def test_05_02_index_name___number(self):
        self.con.flush_schema()
        index = self.sch.get_index('_index', 0)
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index('_index', 2)
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index('_space', 0)
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 1)
        index = self.sch.get_index('_space', 2)
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 1)

        index = self.sch.get_index(self.unicode_space_name_literal,
                                   self.unicode_index_id)
        self.verify_unicode_index(index)

    def test_05_03_index_number_name__(self):
        self.con.flush_schema()
        index = self.sch.get_index(288, 'primary')
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index(288, 'name')
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index(280, 'primary')
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 1)
        index = self.sch.get_index(280, 'name')
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 1)

        index = self.sch.get_index(self.unicode_space_id,
                                   self.unicode_index_name_literal)
        self.verify_unicode_index(index)

    def test_05_04_index_number_number(self):
        self.con.flush_schema()
        index = self.sch.get_index(288, 0)
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index(288, 2)
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index(280, 0)
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 1)
        index = self.sch.get_index(280, 2)
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 1)

        index = self.sch.get_index(self.unicode_space_id,
                                   self.unicode_index_id)
        self.verify_unicode_index(index)

    def test_06_index_cached(self):
        index = self.sch.get_index('_index', 'primary')
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index('_index', 2)
        self.assertEqual(index.space.name, '_index')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 2)
        index = self.sch.get_index(280, 'primary')
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 0)
        self.assertEqual(index.name, 'primary')
        self.assertEqual(len(index.parts), 1)
        index = self.sch.get_index(280, 2)
        self.assertEqual(index.space.name, '_space')
        self.assertEqual(index.iid, 2)
        self.assertEqual(index.name, 'name')
        self.assertEqual(len(index.parts), 1)

        # Verify that no schema fetches occurs.
        self.assertEqual(self.fetch_count, 0)

        cases = (
            (self.unicode_space_name_literal, self.unicode_index_name_literal),
            (self.unicode_space_name_literal, self.unicode_index_id),
            (self.unicode_space_id, self.unicode_index_name_literal),
            (self.unicode_space_id, self.unicode_index_id),
        )
        for s, i in cases:
            index = self.sch.get_index(s, i)
            self.verify_unicode_index(index)

        # Verify that no schema fetches occurs.
        self.assertEqual(self.fetch_count, 0)

    def test_07_schema_version_update(self):
        _space_len = len(self.con.select('_space'))
        self.srv.admin("box.schema.create_space('ttt22')")
        self.assertEqual(len(self.con.select('_space')), _space_len + 1)

    # For schema fetch disable testing purposes.
    testing_methods = {
        'unavailable': {
            'replace': {
                'input': ['tester', (1, None)],
                'output': [[1, None]],
            },
             'delete': {
                'input': ['tester', 1],
                'output': [[1, None]],
            },
            'insert': {
                'input': ['tester', (1, None)],
                'output': [[1, None]],
            }, 
            'upsert': {
                'input': ['tester', (1, None), []],
                'output': [],
            },
            'update': {
                'input': ['tester', 1, []],
                'output': [[1, None]],
            }, 
            'select': {
                'input': ['tester', 1],
                'output': [[1, None]],
            },
            'space': {
                'input': ['tester'],
            },
        },
        'available': {
            # CRUD methods are also tested with the fetch_schema=False opt,
            # see the test_crud.py file.
            'call': {
                'input': ['server_function'],
                'output': [4],
            },
            'eval': {
                'input': ['return 2+2'],
                'output': [4],
            },
            'ping': {
                'input': [],
            },
        },
    }

    def _run_test_schema_fetch_disable(self, con, mode=None):
            # Enable SQL test case for tarantool 2.* and higher.
            if int(self.srv.admin.tnt_version.__str__()[0]) > 1:
                self.testing_methods['available']['execute'] = {
                    'input': ['SELECT * FROM "tester"'],
                    'output': [[1, None]],
                }

            # Testing the schemaless connection with methods
            # that should NOT be available.
            if mode is not None:
                for addr in con.pool.keys():
                    self.assertEqual(con.pool[addr].conn.schema_version, 0)
                    self.assertEqual(con.pool[addr].conn.schema, None)
            else:
                self.assertEqual(con.schema_version, 0)
                self.assertEqual(con.schema, None)
            for method_case in self.testing_methods['unavailable'].keys():
                with self.subTest(name=method_case):
                    if isinstance(con, tarantool.ConnectionPool) and method_case == 'space':
                        continue
                    testing_function = getattr(con, method_case)
                    try:
                        if mode is not None:
                            _ = testing_function(
                                *self.testing_methods['unavailable'][method_case]['input'], 
                                mode=mode)
                        else:
                            _ = testing_function(
                                *self.testing_methods['unavailable'][method_case]['input'])
                    except NotSupportedError as e:
                        self.assertEqual(e.message, 'This method is not available in ' + 
                                                    'connection opened with fetch_schema=False')
            # Testing the schemaless connection with methods
            # that should be available.
            for method_case in self.testing_methods['available'].keys():
                with self.subTest(name=method_case):
                    testing_function = getattr(con, method_case)
                    if mode is not None:
                        resp = testing_function(
                            *self.testing_methods['available'][method_case]['input'], 
                            mode=mode)
                    else:
                        resp = testing_function(
                            *self.testing_methods['available'][method_case]['input'])
                    if method_case == 'ping':
                        self.assertEqual(isinstance(resp, float), True)
                    else:
                        self.assertEqual(
                            resp.data,
                            self.testing_methods['available'][method_case]['output'])

            # Turning the same connection into schemaful.
            if mode is not None:
                for addr in con.pool.keys():
                    con.pool[addr].conn.update_schema(con.pool[addr].conn.schema_version)
            else:
                con.update_schema(con.schema_version)

            # Testing the schemaful connection with methods
            # that should NOW be available.
            for method_case in self.testing_methods['unavailable'].keys():
                with self.subTest(name=method_case):
                    if isinstance(con, tarantool.ConnectionPool) and method_case == 'space':
                        continue
                    testing_function = getattr(con, method_case)
                    if mode is not None:
                        resp = testing_function(
                            *self.testing_methods['unavailable'][method_case]['input'], 
                            mode=mode)
                    else:
                        resp = testing_function(
                            *self.testing_methods['unavailable'][method_case]['input'])
                    if method_case == 'space':
                        self.assertEqual(isinstance(resp, tarantool.space.Space), True)
                    else:
                        self.assertEqual(
                            resp.data, 
                            self.testing_methods['unavailable'][method_case]['output'])
            # Testing the schemaful connection with methods
            # that should have remained available.
            for method_case in self.testing_methods['available'].keys():
                with self.subTest(name=method_case):
                    testing_function = getattr(con, method_case)
                    if mode is not None:
                        resp = testing_function(
                            *self.testing_methods['available'][method_case]['input'], 
                            mode=mode)
                    else:
                        resp = testing_function(
                            *self.testing_methods['available'][method_case]['input'])
                    if method_case == 'ping':
                        self.assertEqual(isinstance(resp, float), True)
                    else:
                        self.assertEqual(
                            resp.data, 
                            self.testing_methods['available'][method_case]['output'])
            if mode is not None:
                self.assertNotEqual(con.pool[addr].conn.schema_version, 1)
                self.assertNotEqual(con.pool[addr].conn.schema, None)
            else:      
                self.assertNotEqual(con.schema_version, 1)
                self.assertNotEqual(con.schema, None)

    def test_08_schema_fetch_disable_via_connection(self):
        self._run_test_schema_fetch_disable(self.con_schema_disable)

    @unittest.skipIf(sys.platform.startswith("win"),
        'Schema fetch disable tests via mesh connection on windows platform are not supported')
    def test_08_schema_fetch_disable_via_mesh_connection(self):
        self._run_test_schema_fetch_disable(self.mesh_con_schema_disable)

    @unittest.skipIf(sys.platform.startswith("win"),
        'Schema fetch disable tests via connection pool on windows platform are not supported')
    def test_08_schema_fetch_disable_via_connection_pool(self):
        self._run_test_schema_fetch_disable(self.pool_con_schema_disable,
                                            mode=tarantool.Mode.ANY)

    @classmethod
    def tearDownClass(self):
        self.con.close()
        self.con_schema_disable.close()
        if not sys.platform.startswith("win"):
            # Schema fetch disable tests via mesh and pool connection
            # are not supported on windows platform.
            self.mesh_con_schema_disable.close()
            self.pool_con_schema_disable.close()
        self.srv.stop()
        self.srv.clean()


class TestSuite_Schema_UnicodeConnection(TestSuite_Schema_Abstract):
    encoding = 'utf-8'


class TestSuite_Schema_BinaryConnection(TestSuite_Schema_Abstract):
    encoding = None
