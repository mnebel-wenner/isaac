import asyncio
import logging

import aiomas
import click

import isaac_util.util as util


@click.command()
@click.option('--start-date', required=True,
              callback=util.validate_start_date,
              help='Start date for the simulation (ISO-8601 compliant, e.g.: '
                   '2010-03-27T00:00:00+01:00')
@click.option('--log-level', '-l', default='debug', show_default=True,
              type=click.Choice(['debug', 'info', 'warning', 'error',
                                 'critical']),
              help='Log level for the MAS')
@click.option('--log-file', '-lf', default='isaac.log', show_default=True,
              help='Log file for the MAS')
@click.argument('addr', metavar='HOST:PORT', callback=util.validate_addr)
def main(addr, start_date, log_level, log_file):
    """

    :param addr: address
    :param start_date: start date
    :param log_level: log_level (string, possibly lower case)
    :param log_file: log file (debug messages will be stored in that file)
    :return:
    """
    initialize_logger(log_level, log_file)
    container_kwargs = util.get_container_kwargs(start_date)
    try:
        aiomas.run(aiomas.subproc.start(addr, **container_kwargs))
    finally:
        asyncio.get_event_loop().close()


def initialize_logger(log_level, log_file):
    """
    Initializes logger
    """
    #set log_level
    logging.getLogger('').setLevel(getattr(logging, log_level.upper()))
    # set file handler
    logging.getLogger('').addHandler(util.get_log_file_handler(log_file))
    # set console handler
    logging.getLogger('').addHandler(util.get_log_console_handler())


if __name__ == '__main__':
    main()
