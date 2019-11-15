from setuptools import setup, find_packages


setup(
    name='isaac',
    version='0.1.0',

    # TODO check, what is really required here
    install_requires=[
        'aiomas[mpb]==1.0.3',
        'arrow>=0.4',
        'click>=4.0',
        'h5py>=2.5',
        'numpy>=1.8',
        'psutil>=2.2',
    ],
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'isaac-mosaik = isaac_mosaik.isaac_mosaik_api:main',
            'isaac-container = isaac_mosaik.container:main',
        ],
    },
)
