import os

import livereload
from flask import Flask, Config, Blueprint, render_template, request
from flask_assets import Environment, Bundle
from webassets.filter import get_filter

from . import utils
from utils import abs_path


default_config = {
    'EA_BOWER_FOLDER': 'bower_components',
    'EA_SCSS_FOLDER': 'scss',
    'EA_CSS_FOLDER': 'css',
    'EA_JS_SRC_FOLDER': 'js_src',
    'EA_JS_FOLDER': 'js',
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
        'slug': 'gen_slug',
        'T': 'translate'
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
    'EA_FOLDER_STRUCTURE': ['static/%{css_folder}s/', 'static/%{scss_folder}s/styles.scss',
                            'static/%{js_folder}s/', 'static/%{js_src_folder}s/Main.js',
                            'static/images/', 'static/fonts/', '%{templates_folder}s/'],
    'EA_JS_LIBS': ['jquery/dist/jquery.min.js'],
    'EA_SCSS_LIBS': ['bootstrap/scss'],

    'EA_FILTER_JSMIN': False,
    'EA_FILTER_AUTOPREFIXER': False,
    'EA_FILTER_BABEL': False,
    'EA_BABEL_PRESETS': '/usr/lib/node_modules/babel-preset-es2015',

    #: Watch files for livereload
    'EA_LIVERELOAD_WATCH_FILES': ['static/%{scss_folder}s/*.scss',
                                  'static/%{js_src_folder}s/*.js',
                                  '%{templates_folder}s/*.html']
}


class EnhancedApp(object):
    """
    Enhanced Flask App with additional jinja filters/function, webassets integration and livereload integration
    """

    #: Flask app
    app = None

    #: webassets environment
    assets_env = None

    _config = None

    is_debug_mode = True

    def __init__(self, app_name='enhanced-flask-app', config_file=None, debug_mode=True, **flask_kwargs):
        self.is_debug_mode = debug_mode
        config = Config('.', Flask.default_config)
        if config_file:
            config.from_object(config_file)

        for k, v in default_config.items():
            config.setdefault(k, v)

        self._config = config.get_namespace('EA_')

        self.create_folder_structure()

        flask_kwargs.setdefault('static_folder', self._config['prefix'] + 'static')
        flask_kwargs.setdefault('static_url_path', '/static')
        flask_kwargs.setdefault('template_folder', self._config['prefix'] + 'templates')

        self.app = Flask(app_name, **flask_kwargs)

        self.app.config = config
        self.add_error_handlers()

        # Create webassets
        self.assets_env = Environment(self.app)
        self.enhance_assets(self.assets_env)

        # Initialize additional jinja stuff
        self.enhance_jinja(self.app.jinja_env)

        # Add a blueprint to hook up default HTML template
        bp = Blueprint('enhanced-flask-app-bp', __name__, template_folder=utils.abs_path('templates', __file__))
        self.app.register_blueprint(bp)

    def create_folder_structure(self):
        for f in self._config['folder_structure']:
            _path = self._config['prefix'] + f % self._config
            if os.path.exists(_path):
                break
            self._create_path(_path)

    def enhance_jinja(self, env):
        self.app.jinja_loader.searchpath.append(abs_path('templates', __file__))
        # Add a parameter if jinja is in debug mode so the webassets will serve static files instead of compiling them
        env.globals['debug_mode'] = self.is_debug_mode
        # Turn on auto reload when developing in local machine
        env.auto_reload = env.globals['debug_mode']

        # Add custom tags/blocks
        env.add_extension('jinja2_ext_required.RequiredVariablesExtension')

        # Add additional jinja filters
        for k, v in self._config['jinja_filters'].items():
            env.filters[k] = getattr(utils, v)

        for k, v in self._config['jinja_functions'].items():
            env.globals[k] = getattr(utils, v)

        #: Initialize jinja context
        @self.app.context_processor
        def gen_jinja_context():
            obj = {}
            for _k, _v in self._config['jinja_context'].items():
                obj[_k] = getattr(utils, _v)
            return obj

    def enhance_assets(self, env):
        """
        Add js, css/scss assets to the environment
        :param env:     webassets environment
        :return:
        """

        scss_path = abs_path(self._to_static_path(self._config['scss_folder']))
        css_path = abs_path(self._to_static_path(self._config['css_folder']))
        js_src_path = abs_path(self._to_static_path(self._config['js_src_folder']))
        js_path = abs_path(self._to_static_path(self._config['js_folder']))
        bower_path = abs_path(self._config['bower_folder'])

        js_filters = []
        if self._config['use_jsmin']:
            js_filters = ['jsmin']

        if self._config['use_babel']:
            js_filters.append(get_filter('babel', presets=self._config['babel_presets']))

        libs = [os.path.join(bower_path, f) for f in self._config['js_libs']]
        #: Project specific libs added in project config
        if libs:
            output_file = os.path.join(js_path, 'libs.js')
            if os.path.exists(output_file) and self.is_debug_mode:
                os.remove(output_file)
            b = Bundle(libs, output=output_file, filters=js_filters)
            env.register('libs-js', b)

        scripts = []

        for f in sorted(os.listdir(js_src_path), reverse=True):
            if f.lower()[-2:] == 'js':
                scripts.append(os.path.join(js_src_path, f))
        if scripts:
            output_file = os.path.join(js_path, 'scripts.js')
            if os.path.exists(output_file) and self.is_debug_mode:
                os.remove(output_file)
            b = Bundle(scripts, output=output_file, filters=js_filters)
            env.register('scripts-js', b)

        include_scss = [scss_path]
        depends_scss = [os.path.join(scss_path, '*.scss')]
        for f in self._config['scss_libs']:
            include_scss.append(os.path.join(bower_path, f))
            depends_scss.append(os.path.join(bower_path, f, '*.scss'))
        sass_compiler = get_filter('libsass', includes=include_scss)

        css_filters = [sass_compiler]

        if self._config['use_autoprefixer']:
            css_filters.append(get_filter('autoprefixer', autoprefixer='autoprefixer-cli', browsers='last 2 version'))

        b = Bundle(os.path.join(scss_path, 'styles.scss'),
                   filters=css_filters, depends=depends_scss,
                   output=os.path.join(css_path, 'styles.css'))
        env.register('styles-css', b)

    def run_livereload(self, port=8080, debug=True):
        """
        Create a live reload server
        :param additional_files:    list of file patterns, relative to the project's root
        :return:
        """
        server = livereload.Server(self.app)
        for f in self._config['livereload_watch_files']:
            if f.startswith('static') or f.startswith('template'):
                f = self._config['prefix'] + f
            server.watch(abs_path(f))
        self.app.debug = debug
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
        return os.path.join(self._config['prefix'] + 'static', *filenames)