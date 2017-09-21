import os
import glob
import collections

import livereload
from flask import Flask, Config, Blueprint, render_template, request
from flask_assets import Environment, Bundle
from webassets.filter import get_filter

from . import utils
from utils import abs_path


default_config = {
    'EA_BOWER_FOLDER': 'bower_components',
    'EA_SCSS_FOLDER': 'scss',
    'EA_JS_SRC_FOLDER': 'js_src',
    'EA_TEMPLATES_FOLDER': 'templates',
    #: Path prefix for static and template folder
    #: This is very useful place multiple apps within one folder
    #: For most of my projects, I will need one app for the user facing side and one for admin side
    'EA_PREFIX': '',
    #: Custom Jinja filters
    'EA_JINJA_FILTERS': {
        'breaks': 'add_br',
        'copyright': 'copyright_year',
        'currency': 'format_currency',
        'date': 'format_date',
        'datetime': 'format_datetime',
        'http': 'add_http',
        'https': 'add_https',
        'leading_zero': 'leading_zero',
        'paragraphs': 'add_p',
        'no_breaks': 'remove_linebreaks',
        'slug': 'gen_slug'
    },
    #: Custom Jinja global functions
    'EA_JINJA_FUNCTIONS': {'next_year': 'next_year',
                           'random_string': 'random_string',
                           'gen_years': 'relative_years',
                           },
    #: Add some parameters and functions to jinja context because
    #: the functions behaves differently with each request
    'EA_JINJA_CONTEXT': {'highlight': 'highlight_link'},

    #: Project folder structure
    'EA_FOLDER_STRUCTURE': ['%(prefix)sstatic/', '%(prefix)sstatic/%(scss_folder)s/styles.scss',
                            '%(prefix)sstatic/', '%(prefix)sstatic/%(js_src_folder)s/Main.js',
                            '%(prefix)sstatic/images/', '%(prefix)sstatic/fonts/', '%(prefix)s%(templates_folder)s/'],
    'EA_JS_LIBS': ['jquery/dist/jquery.min.js'],
    'EA_SCSS_LIBS': ['bootstrap/scss'],

    'EA_JS_ASSETS': [('scripts.js', '*.js')],
    'EA_CSS_ASSETS': ['styles.scss'],

    'EA_FILTER_JSMIN': False,
    'EA_FILTER_AUTOPREFIXER': False,
    'EA_FILTER_BABEL': False,
    'EA_BABEL_PRESETS': '/usr/local/lib/node_modules/babel-preset-es2015',

    #: Watch files for livereload
    'EA_LIVERELOAD_WATCH_FILES': ['%(prefix)sstatic/%(scss_folder)s/*.scss',
                                  '%(prefix)sstatic/%(js_src_folder)s/*.js',
                                  '%(prefix)s%(templates_folder)s/*.html']
}


class EnhancedApp(object):
    """
    Enhanced Flask App with additional jinja filters/function, webassets integration and livereload integration
    """

    def __init__(self, app_name='enhanced-flask-app', config_file=None, **flask_kwargs):
        config = Config('.', Flask.default_config)
        if config_file:
            config.from_object(config_file)

        for k, v in default_config.items():
            config.setdefault(k, v)

        self.config = config.get_namespace('EA_')

        self.create_folder_structure()

        flask_kwargs.setdefault('static_folder', self.config['prefix'] + 'static')
        flask_kwargs.setdefault('static_url_path', '/static')
        flask_kwargs.setdefault('template_folder', self.config['prefix'] + 'templates')

        self.app = Flask(app_name, **flask_kwargs)
        self.app.config = config

        # Create webassets
        self.assets_env = Environment(self.app)
        self.assets_env.url_expire = True
        self.assets_env.url = '/static'
        self.assets_env

        # Initialize additional jinja stuff
        self.enhance_jinja(self.app.jinja_env)

        # Add a blueprint to hook up default HTML template
        bp = Blueprint('enhanced-flask-app-bp', __name__, template_folder=utils.abs_path('templates', __file__))
        self.app.register_blueprint(bp)

        # Flask assets related
        self.scss_path = abs_path(self._to_static_path(self.config['scss_folder']))
        self.js_src_path = abs_path(self._to_static_path(self.config['js_src_folder']))
        self.bower_path = abs_path(self.config['bower_folder'])
        self.js_filters = []
        self.css_filters = []
        self.depends_scss = []

        # Keep track of js, css bundles added in sequence
        # esp important for js because of the dependencies
        self.js_asset_names = []
        self.css_asset_names = []

        self.enhance_assets()

    def create_folder_structure(self):
        for f in self.config['folder_structure']:
            _path = f % self.config
            if os.path.exists(_path):
                break
            self._create_path(_path)

    def enhance_jinja(self, env):
        # Add custom tags/blocks
        env.add_extension('jinja2_ext_required.RequiredVariablesExtension')

        # Add additional jinja filters
        for k, v in self.config['jinja_filters'].items():
            env.filters[k] = getattr(utils, v)

        for k, v in self.config['jinja_functions'].items():
            env.globals[k] = getattr(utils, v)

        #: Initialize jinja context
        @self.app.context_processor
        def gen_jinja_context():
            obj = {}
            for _k, _v in self.config['jinja_context'].items():
                obj[_k] = getattr(utils, _v)
            return obj

    def enhance_assets(self):
        """
        Add js, css/scss assets to the environment
        :param env:     webassets environment
        :return:
        """
        if self.config['filter_jsmin']:
            self.js_filters = ['jsmin']

        if self.config['filter_babel']:
            self.js_filters.append(get_filter('babel', presets=self.config['babel_presets']))

        include_scss = [self.scss_path]
        self.depends_scss = [os.path.join(self.scss_path, '*.scss')]
        for f in self.config['scss_libs']:
            include_scss.append(os.path.join(self.bower_path, f))
            self.depends_scss.append(os.path.join(self.bower_path, f, '*.scss'))
        sass_compiler = get_filter('libsass', includes=include_scss)

        self.css_filters = [sass_compiler]

        if self.config['filter_autoprefixer']:
            self.css_filters.append(
                get_filter('autoprefixer', autoprefixer='autoprefixer-cli', browsers='last 2 version'))

        #: Project specific libs added in project config
        libs = [os.path.join(self.bower_path, f) for f in self.config['js_libs']]
        if libs:
            self.add_js_asset('libs.js', libs)

        #: JS assets
        for asset in self.config['js_assets']:
            self.add_js_asset(asset[0], asset[1])

        #: CSS assets
        for asset in self.config['css_assets']:
            self.add_css_asset(asset)

    def add_js_asset(self, output_file, input_files):
        if isinstance(input_files, basestring):
            scripts = glob.glob(os.path.join(self.js_src_path, input_files))
            sorted(scripts, reverse=True)
        else:
            scripts = input_files
        b = Bundle(scripts, output=self._to_static_path(output_file), filters=self.js_filters)
        self.assets_env.register(output_file, b)
        self.js_asset_names.append(output_file)

    def add_css_asset(self, base_file):
        input_file = base_file + '.scss'
        output_file = base_file + '.css'
        b = Bundle(os.path.join(self.scss_path, input_file),
                   filters=self.css_filters, depends=self.depends_scss,
                   output=self._to_static_path(output_file))
        self.assets_env.register(output_file, b)
        self.css_asset_names.append(output_file)

    def run_livereload(self, port=8080):
        """
        Create a live reload server
        :param additional_files:    list of file patterns, relative to the project's root
        :return:
        """
        self.app.debug = True
        self.app.jinja_env.globals['livereload'] = True
        self.app.jinja_env.auto_reload = True
        server = livereload.Server(self.app.wsgi_app)
        for f in self.config['livereload_watch_files']:
            server.watch(abs_path(f % self.config))
        server.serve(port=port, host='0.0.0.0')

    def add_error_handlers(self):
        @self.app.errorhandler(410)
        def content_gone(e):
            return render_template('410.html', error=e), 410

        @self.app.errorhandler(403)
        def access_denied(e):
            return render_template('403.html', error=e), 403

        @self.app.errorhandler(404)
        def content_not_found(e):
            if request.path == '/favicon.ico':
                return 'Not found', 404
            return render_template('404.html', error=e), 404

    def _create_path(self, path):
        if os.path.exists(path):
            return
        parent = os.path.abspath(os.path.join(path, os.pardir))
        while not os.path.exists(parent):
            self._create_path(parent)
        # Check if the path is a file
        if path.rfind('.') > path.rfind(os.path.sep):
            open(path, 'w').close()
        else:
            os.mkdir(path)

    def _to_static_path(self, *filenames):
        return os.path.join(abs_path(self.config['prefix'] + 'static'), *filenames)
