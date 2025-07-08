from setuptools import setup

setup(
    name='yt-transcribe',
    version='0.1',
    py_modules=['cli'],
    install_requires=[
        'boto3',
        'python-dotenv',
        'requests',
        'requests-auth-aws-sigv4'
    ],
    entry_points={
        'console_scripts': [
            'yt-transcribe = cli:main',
        ],
    },
)
