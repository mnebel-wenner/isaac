import isaac_standalone.config as config
import h5py
import numpy as np
import matplotlib.pyplot as pl
import matplotlib.backends.backend_pdf
import os

f = h5py.File(config.DB_FILE, 'r')
for number, negotiation in enumerate(config.NEGOTIATIONS):
    # open corresponding group
    day_results = f.get('dap/%s/' % negotiation['date'])

    # get results for cs, ts, dap results and agent details
    cs_results = np.array(day_results.get('cs'))
    ts_results = np.array(day_results.get('ts'))
    dap_results = np.array(day_results.get('dap_data'))
    agent_details = np.array(day_results.get('Agent details'))

    # one figure per negotiation
    pl.figure(number, figsize=(20, 20))
    pl.suptitle('Results for %s' % negotiation['date'], fontsize=18, fontweight='bold')

    # 1. subplot - os of all agents
    # create a dictionary: schedule index in cs: name of agent
    # in order to label the plot correctly
    idx_dict = {}
    for details in agent_details:
        idx_dict[details['Index in cs']] = details['Name'].decode()
    pl.subplot(221)
    pl.xlabel('Interval', fontweight='bold', fontsize=12)
    pl.ylabel('Power output', fontweight='bold', fontsize=12)
    pl.title('Cluster Schedule', fontsize=16)
    pl.grid()
    # a different marker for each plot - it may help to see overlapping plots
    markers = ['o', '+', 'h', 's', 'x', 'D']
    for i in range(len(cs_results)):
        pl.plot(cs_results[i], '%c-' % markers[i % len(markers)], label=idx_dict[i], linewidth=2.0, alpha=0.9)
    pl.legend(fontsize=12)

    # 2. subplot: ts and aggregated result
    ts = ts_results['target schedule']
    # weights = ts_results['weights']   # weights are not plotted so far
    ax = pl.subplot(222)
    pl.xlabel('Interval', fontweight='bold', fontsize=12)
    pl.ylabel('Power output', fontweight='bold', fontsize=12)
    pl.title('Target schedule and aggregated result', fontsize=16)
    # plot target schedule
    pl.plot(ts, 'o-', label='Target Schedule', linewidth=2.0)
    # get sum of clustered schedule and plot it
    aggregated_result = np.sum(cs_results, axis=0)
    pl.plot(aggregated_result, 'o-', label='Aggregated result', linewidth=2.0)
    pl.legend(fontsize=14)
    pl.grid()
    ax.axhline(0, linestyle='-', color='black', linewidth=1.0)

    # 3. subplot: deviation from target
    ax = pl.subplot(223)
    difference = np.subtract(aggregated_result, ts)
    pl.xlabel('Interval', fontweight='bold')
    pl.ylabel('Power output', fontweight='bold')
    pl.title('Deviation from target', fontsize=16)
    pl.plot(difference, 'o-', label='deviation', linewidth=2.5)
    pl.grid()
    ax.axhline(0, linestyle='-', color='black', linewidth=3.0)

    # 4. subplot: development of performance
    ax = pl.subplot(224)
    pl.xlabel('Process time [s]', fontweight='bold', fontsize=12)
    pl.ylabel('Performance of candidate of active agent', fontweight='bold', fontsize=12)
    pl.title('Performance development', fontsize=16)
    # get lists for time and performance
    time_data = [data['t'] for data in dap_results]
    performance_data = [data['perf'] for data in dap_results]
    # get ticks where the agents knowledge is not complete
    time_not_complete = [i for i, data in enumerate(dap_results) if not data['complete']]
    # get ticks where the agents knowledge is complete and he has sent a message
    time_complete_msg_sent = [i for i, data in enumerate(dap_results) if data['complete'] and data['msg_sent']]
    # get ticks where the agents knowledge is complete and he has not sent a message
    time_complete_no_msg_sent = [i for i, data in enumerate(dap_results) if data['complete'] and not data['msg_sent']]

    # plot line for performance development
    pl.plot(time_data, performance_data, '-', linewidth=2.5, label='current performance')
    # mark every point for not complete
    pl.plot(time_data, performance_data, 'rD', markevery=time_not_complete, label='information not complete')
    # mark every point for complete and sending message
    pl.plot(time_data, performance_data, 'yD', markevery=time_complete_msg_sent,
            label='complete information, sending messages')
    # mark every point for complete and no message sent
    pl.plot(time_data, performance_data, 'gD', markevery=time_complete_no_msg_sent,
            label='complete information, no message sent')

    # plot a box with the final result of the performance.
    pl.text(
        0.95, 0.25,
        'Final performance:\n%s' % "{:,}".format(performance_data[-1]),
        transform=ax.transAxes, fontsize=18, verticalalignment='bottom',
        horizontalalignment='right', bbox={'facecolor': 'red', 'alpha': 0.75, 'pad': 10})
    pl.grid()
    pl.legend(fontsize=14)

# print all results in one pdf file called results.pdf
pdf = matplotlib.backends.backend_pdf.PdfPages(os.path.join(config.RESULT_PATH, 'results.pdf'))
for fig in range(len(config.NEGOTIATIONS)):
    pdf.savefig(fig)
pdf.close()
