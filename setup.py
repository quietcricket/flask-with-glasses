from setuptools import setup, find_packages

print find_packages()
setup(
    name='Flask With Glasses',
    version='0.1.1',
    description='Enhanced flask app with livereload and webassets. More suitable for front end development',
    author='Shang Liang',
    author_email='shang@wewearglasses.com',
    url='https://github.com/wewearglasses/flask-with-glasses',
    license='MIT',
    packages=['flask_with_glasses'],
    zip_safe=False,
    include_package_data=True,
    install_requires=['flask', 'flask-assets', 'livereload'],
    classifiers=['Development Status :: 3 - Alpha'],
)