"""Command line tools for repositories on GitHub and Bitbucket and packages on Packagist.

Each service is a subpackage with an api module, which the other services may call, and a
commands package, with one module per subcommand. forge.py is what every code host's delivery
data is read through, and forge_commands.py the commands that read it.
"""
