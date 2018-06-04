#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Time        : 2017/11/30 下午12:20
# @Author      : Zoe
# @File        : wande-event.py
# @Description : 1. 训练测试集按2017年划分 ok
#                 2. 抽取batch的方法：只用每次shuffle的时候，training accuracy才高？？？
#                   3. Recall@10  / 换成大类 / testing accuracy = 0.581037
#                       4. self-attention LSTM model
#                           5. 求 阿尔法 ，分别基于 事件/位置/时间信息。
                # 需要修改：20 / LSTM

# TODO 做一些baseline 语言模型n-gram / 只猜概率最大的数据 / 数据集分析

# 21669/85882 = 0.2523

import json
import pickle
import datetime
import time
import collections
import numpy as np
import tensorflow as tf
import random
import matplotlib.pyplot as plt
import os,sys,getopt
import config
from sklearn import preprocessing

flags = tf.app.flags
FLAGS = flags.FLAGS

# dev或test数据集
opts, args = getopt.getopt(sys.argv[1:], "t:n:c:v:", ["type=","note=","cf=","cuda="])
trainType = 'event'
note = ''
classifier = 'mlp'
cuda = '3'
for op, value in opts:
    if op == "--type":
        trainType = value
    if op == '--note':
        note = value
    if op == '--cf':
        classifier = value
    if op == '--cuda':
        cuda = value

model_save_path = '../data/ckpt-att/'+trainType+classifier+note+'.ckpt'
os.environ["CUDA_VISIBLE_DEVICES"] = cuda

config = tf.ConfigProto(log_device_placement=True, allow_soft_placement=True)
config.gpu_options.per_process_gpu_memory_fraction = 0.9 # 占用GPU90%的显存
config.gpu_options.allow_growth = True


def extract_one_company():
    f = open('/Users/zoe/Documents/event_extraction/majorEventDump/majorEventDump.json','r')
    a = f.read()
    f.close()

    f = open('/Users/zoe/Documents/event_extraction/majorEventDump/typeCodeDump.json','r')
    b = f.read()
    f.close()

    majorEvent = json.loads(a)
    typeCode = json.loads(b)

    # {'S_INFO_WINDCODE': '000418.SZ', 'S_EVENT_HAPDATE': '20140815', 'S_EVENT_EXPDATE': '20140815', 'S_EVENT_CATEGORYCODE': '204008001'}

    type = set()
    dic = list()

    for one in majorEvent:
        if one['S_INFO_WINDCODE'] == '601988.SH':
            d = dict()
            d['S_INFO_WINDCODE'] = one['S_INFO_WINDCODE']
            d['S_EVENT_HAPDATE'] = one['S_EVENT_HAPDATE']
            d['S_EVENT_EXPDATE'] = one['S_EVENT_EXPDATE']
            d['S_EVENT'] = typeCode[one['S_EVENT_CATEGORYCODE']]
            if typeCode[one['S_EVENT_CATEGORYCODE']] not in type:
                type.add(typeCode[one['S_EVENT_CATEGORYCODE']])
            dic.append(d)

    print(type)
    print(len(type))
    f = open('event.txt', 'w')
    for one in dic:
        f.write(json.dumps(one,ensure_ascii=False)+'\n')
    f.close()


def test():
    with open('/Users/zoe/Documents/event_extraction/majorEventDump/majorEventDump.json', 'r') as f:
        majorEvent = json.load(f)
    with open('/Users/zoe/Documents/event_extraction/majorEventDump/typeCodeDump.json', 'r') as f:
        typeCode = json.load(f)

    # {'S_INFO_WINDCODE': '000859.SZ', 'S_EVENT_HAPDATE': '20121231', 'S_EVENT_EXPDATE': '20160105',
    #  'S_EVENT_CATEGORYCODE': '204011005' 股权转让完成}
    # {'S_INFO_WINDCODE': '600610.SH', 'S_EVENT_HAPDATE': '19970418', 'S_EVENT_EXPDATE': '19901231',
    #  'S_EVENT_CATEGORYCODE': '204006021' 披露年报}
    type = set()
    dicMax = dict()
    dicMin = dict()
    maxInterval = 0
    minInterval = 0
    # for one in majorEvent:
    #     if one['S_INFO_WINDCODE'] == '600610.SH' and one['S_EVENT_HAPDATE'] == '19970418':
    #         print(one)
    #         print(typeCode[one['S_EVENT_CATEGORYCODE']])
    for one in majorEvent:
        try:
            hap = datetime.datetime.strptime(one['S_EVENT_HAPDATE'], '%Y%m%d')
            exp = datetime.datetime.strptime(one['S_EVENT_EXPDATE'], '%Y%m%d')
            if (exp-hap).days > maxInterval:
                maxInterval = (exp-hap).days
                dicMax = one
            if (exp-hap).days < minInterval:
                minInterval = (exp-hap).days
                dicMin = one
        except:
            print(one)
    print(dicMax)
    print(dicMin)


def generat_class():
    with open('/Users/zoe/Documents/event_extraction/majorEventDump/Class.txt', 'r') as f_r:
        typeClass = collections.defaultdict(list)
        typeList = list()
        for line in f_r.readlines():
            if line != '\n':
                typeList.append(line.strip())
            else:
                typeClass[typeList[0]] = typeList[1:]
                typeList = list()
        print(typeClass)

    with open('/Users/zoe/Documents/event_extraction/majorEventDump/Class.json', 'w') as f_w:
        json.dump(typeClass, f_w, indent=1, ensure_ascii=False)


def minifile():
    with open('/Users/zoe/Documents/event_extraction/majorEventDump/majorEventDump.json', 'r',
              encoding='utf-8') as inputFile:
        events = json.load(inputFile)

    eventsGroupByCompany = collections.defaultdict(list)

    for event in events:
        try:
            company = event['S_INFO_WINDCODE']
            parseEvent = {
                'type': event['S_EVENT_CATEGORYCODE'],
                'date': datetime.datetime.strptime(event['S_EVENT_HAPDATE'], '%Y%m%d'),
            }
            eventsGroupByCompany[company].append(parseEvent)
        except:
            continue

### 为了统计最早最晚事件、平均事件时间间隔、事件频率 ###

    minDate = datetime.datetime.now()
    minEvent = dict()
    maxDate = datetime.datetime.strptime('20160101', '%Y%m%d')
    maxEvent = dict()
    intervalDate = 0
    eventDict = dict()
    for company, eventSeq in eventsGroupByCompany.items():
        sortedEventSeq = sorted(eventSeq, key=lambda e: e['date'])

        for index, event in enumerate(sortedEventSeq):
            if datetime.datetime.strftime(event['date'], '%Y%m%d') not in eventDict:
                eventDict[datetime.datetime.strftime(event['date'], '%Y%m%d')] = 1
            else:
                eventDict[datetime.datetime.strftime(event['date'], '%Y%m%d')] += 1
            if index > 0:
                intervalDate += (event['date']-lastDate).days
            if event['date'] < minDate:
                minDate = event['date']
                minEvent = event
                minEvent['company'] = company
            if event['date'] > maxDate:
                maxDate = event['date']
                maxEvent = event
                maxEvent['company'] = company
            lastDate = event['date']

    # with open('/Users/zoe/Documents/event_extraction/majorEventDump/eventCount.json', 'w',
    #           encoding='utf-8') as inputFile:
    #     json.dump(eventDict, inputFile, indent=1)

    print(intervalDate)
    print(minEvent)
    print(maxEvent)

### 共 3556 个公司，2342415个事件，总间隔15278034天,平均事件间隔6.52天
    # 1987 - 12 - 22  {'type': '204002012', 'date': datetime.datetime(1987, 12, 22, 0, 0)，'company': '000633.SZ'}
    # 2017 - 12 - 29  {'type': '204008004', 'date': datetime.datetime(2017, 12, 29, 0, 0)，'company': '601727.SH'}

    companyNum = 1000
    companyIndex = 0
    companyDict = dict()

    with open('/Users/zoe/Documents/event_extraction/majorEventDump/majorEventAll.json', 'w') as outputFile:
        allDict = list()
        for company, eventSeq in eventsGroupByCompany.items():
            print(company)
            # if companyIndex > companyNum:
            #     break
            companyIndex += 1
            sortedEventSeq = sorted(eventSeq, key=lambda e: e['date'])
            for e in sortedEventSeq:
                e['date'] = datetime.datetime.strftime(e['date'], '%Y%m%d')
            companyDict['S_INFO_WINDCODE'] = company
            companyDict['event'] = sortedEventSeq
            allDict.append(companyDict)
            companyDict = dict()
        json.dump(allDict, outputFile, indent=1)

# minifile()


def plot():
    with open('/Users/zoe/Documents/event_extraction/majorEventDump/eventCount.json', 'r',
              encoding='utf-8') as inputFile:
        eventCount = json.load(inputFile)

    keys = eventCount.keys()
    vals = eventCount.values()
    eventList = [(key, val) for key, val in zip(keys, vals)]
    sortedEvent = sorted(eventList, key=lambda e:e[0])
    y = [val for key,val in sortedEvent]
    print(len(y))
    x = range(0, len(y))
    plt.plot(x, y, '')
    plt.xticks((0, 2200, 4400, 6600, 8800), ('1987-12', '1995-06', '2002-12', '2010-06', '2017-12'))
    plt.xlabel('date')
    plt.ylabel('count')
    plt.title('Events per day')
    plt.show()


# plot()


def get_xy():
    # global Category
    # global Chain_Lens

    with open('/Users/zoe/Documents/event_extraction/majorEventDump/majorEvent50.json', 'r',
              encoding='utf-8') as inputFile:
        events = json.load(inputFile)

    with open('/Users/zoe/Documents/event_extraction/majorEventDump/typeCodeDump.json', 'r',
              encoding='utf-8') as inputFile:
        code2type = json.load(inputFile)

    with open('/Users/zoe/Documents/event_extraction/majorEventDump/Class.json', 'r') as inputFile:
        typeClass = json.load(inputFile)

### 获得按时间排序的公司事件链条
    eventsGroupByCompany = collections.defaultdict(list)
    for event in events:
        company = event['S_INFO_WINDCODE']
        parseEvent = event['event']
        eventsGroupByCompany[company] = parseEvent

    for company, eventSeq in eventsGroupByCompany.items():
        for event in eventSeq:
            if event['type'] not in Category:
                Category[event['type']] = len(Category)
            event['type'] = Category[event['type']]
            # event['date'] = datetime.datetime.strptime(event['date'], '%Y%m%d')

    x_mat_list = list()
    x_mat = np.zeros(shape=(Chain_Lens))
    y_tag_list = list()
    y_tag = np.zeros(shape=(len(Category)))
    x_test = list()
    y_test = list()

    for company, eventSeq in eventsGroupByCompany.items():
        if len(eventSeq) > Chain_Lens:
            ratio = (int)(len(eventSeq) * 0.7)
            for beginIdx, e in enumerate(eventSeq[:ratio]):
                if beginIdx >= Chain_Lens:
                    for i in range(Chain_Lens):
                        x_mat[Chain_Lens - i - 1] = eventSeq[beginIdx - i - 1]['type']
                    x_mat_list.append(x_mat)
                    x_mat = np.zeros(shape=(Chain_Lens))
                    y_tag[e['type']] = 1
                    y_tag_list.append(y_tag)
                    y_tag = np.zeros(shape=(len(Category)))

            for beginIdx, e in enumerate(eventSeq[ratio:]):
                if beginIdx >= Chain_Lens:
                    for i in range(Chain_Lens):
                        x_mat[Chain_Lens - i - 1] = eventSeq[beginIdx - i - 1]['type']
                    x_test.append(x_mat)
                    x_mat = np.zeros(shape=(Chain_Lens))
                    y_tag[e['type']] = 1
                    y_test.append(y_tag)
                    y_tag = np.zeros(shape=(len(Category)))

    return np.array(x_mat_list).astype(int), np.array(y_tag_list).astype(int),\
           np.array(x_test).astype(int),np.array(y_test).astype(int)


def get_xy_new():

    with open('../data/TrainSet.json', 'r',
              encoding='utf-8') as inputFile:
        eventsTrain = json.load(inputFile)
    with open('../data/TestSet.json', 'r',
              encoding='utf-8') as inputFile:
        eventsTest = json.load(inputFile)

    for company, eventSeq in eventsTest.items():
        for event in eventSeq:
            if event['type'] not in Category:
                Category[event['type']] = len(Category)
            event['type'] = Category[event['type']]
    for company, eventSeq in eventsTrain.items():
        for event in eventSeq:
            if event['type'] not in Category:
                Category[event['type']] = len(Category)
            event['type'] = Category[event['type']]

    x_mat_list = list()
    x_mat = np.zeros(shape=(Chain_Lens*2))
    y_tag_list = list()
    y_tag = np.zeros(shape=(len(Category)))
    x_test = list()
    y_test = list()

    # ********数据链条的生成********
    for company, eventSeq in eventsTrain.items():
        if len(eventSeq) > Chain_Lens:
            for beginIdx, e in enumerate(eventSeq):
                if beginIdx >= Chain_Lens:
                    for i in range(Chain_Lens):
                        x_mat[Chain_Lens - i - 1] = eventSeq[beginIdx - i - 1]['type']
                    Start_Date = datetime.datetime.strptime(eventSeq[beginIdx-5]['date'], '%Y%m%d')
                    for i in range(Chain_Lens):
                        This_Date = datetime.datetime.strptime(eventSeq[beginIdx - i - 1]['date'], '%Y%m%d')
                        timeDelta = 0
                        if This_Date-Start_Date < datetime.timedelta(4):
                            timeDelta = 1
                        elif This_Date-Start_Date < datetime.timedelta(8):
                            timeDelta = 2
                        elif This_Date-Start_Date < datetime.timedelta(31):
                            timeDelta = 3
                        else:
                            timeDelta = 4
                        x_mat[Chain_Lens - i + 4] = timeDelta
                    x_mat_list.append(x_mat)
                    x_mat = np.zeros(shape=(Chain_Lens*2))
                    y_tag[e['type']] = 1
                    y_tag_list.append(y_tag)
                    y_tag = np.zeros(shape=(len(Category)))

    for company, eventSeq in eventsTest.items():
        if len(eventSeq) > Chain_Lens:
            for beginIdx, e in enumerate(eventSeq):
                if beginIdx >= Chain_Lens:
                    for i in range(Chain_Lens):
                        x_mat[Chain_Lens - i - 1] = eventSeq[beginIdx - i - 1]['type']
                    Start_Date = datetime.datetime.strptime(eventSeq[beginIdx - 5]['date'], '%Y%m%d')
                    for i in range(Chain_Lens):
                        This_Date = datetime.datetime.strptime(eventSeq[beginIdx - i - 1]['date'], '%Y%m%d')
                        timeDelta = 0
                        if This_Date - Start_Date < datetime.timedelta(4):
                            timeDelta = 1
                        elif This_Date - Start_Date < datetime.timedelta(8):
                            timeDelta = 2
                        elif This_Date - Start_Date < datetime.timedelta(31):
                            timeDelta = 3
                        else:
                            timeDelta = 4
                        x_mat[Chain_Lens - i + 4] = timeDelta
                    x_test.append(x_mat)
                    x_mat = np.zeros(shape=(Chain_Lens*2))
                    y_tag[e['type']] = 1
                    y_test.append(y_tag)
                    y_tag = np.zeros(shape=(len(Category)))

    return np.array(x_mat_list).astype(int), np.array(y_tag_list).astype(int),\
           np.array(x_test).astype(int),np.array(y_test).astype(int)

# x_mat_list, y_tag_list, x_test, y_test = get_xy_new()

# TODO 数据按（00，17）划分 .new 数据集 ok
f_data = open('../data/pickle.data.SC.train', 'rb')
x_mat_list = pickle.load(f_data)
y_tag_list = pickle.load(f_data)
f_data.close()

print('***DATA SHAPE***\n', x_mat_list.shape, y_tag_list.shape)

# # # 生成Category.json文件。换成pickle data后，直接载入之前生成的Category.json。
# # with open('../data/Category.json', 'w', encoding='utf-8') as outputFile:
# #     json.dump(Category, outputFile, indent=1)
# with open('../data/Category.json','r') as inputFile:
#     Category = json.load(inputFile)

# shuffle x y
def shuffle_xy(x_mat_list, y_tag_list):
    zip_list = list(zip(x_mat_list, y_tag_list))
    random.shuffle(zip_list)
    x_mat_list[:], y_tag_list[:] = zip(*zip_list)
    return x_mat_list, y_tag_list

#TODO 参数大小调整 ok
# lr = 0.001
# 需要改大
# epoch = 1
# _batch_size = 128
training_iters = x_mat_list.shape[0] / FLAGS._batch_size
# vocab_size = 25    # 样本中事件类型个数，根据处理数据的时候得到
# embedding_size = 20
trainNum = 100000
# Chain_Lens = 5

# n_steps = Chain_Lens # 链条长度
# n_hidden_units = 128 # 神经元数目
# n_classes = 25

# x_mat_list = x_mat_list[-100000:]
# y_tag_list = y_tag_list[-100000:]

x = tf.placeholder(tf.int32, [None, FLAGS.n_steps*2])
y = tf.placeholder(tf.int32, [None, FLAGS.n_classes])
output_kp = tf.placeholder(tf.float32, [])

# TODO 看一下参数的训练过程 ok
weights = {
    # （feature_dim，128）
    'weight_add': tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
    'baseline_gcn': tf.Variable(tf.random_normal([FLAGS.n_hidden_units + FLAGS.embedding_size, FLAGS.n_hidden_units])),
    'attention': tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
    'attention_2': tf.Variable(tf.random_normal([FLAGS.n_hidden_units, 1])),
    # 'baseline': tf.Variable(tf.random_normal([n_hidden_units * 2, n_hidden_units])),
    # 'position': tf.Variable(tf.random_normal([FLAGS.n_hidden_units * 2, FLAGS.n_hidden_units])),
    # 'time': tf.Variable(tf.random_normal([n_hidden_units * 3, n_hidden_units])),
    # 'event': tf.Variable(tf.random_normal([n_hidden_units * 3, n_hidden_units])),

    # （128，n_classes）
    'out': tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_classes])),
    'out_gcn': tf.Variable(tf.random_normal([FLAGS.n_hidden_units, 1]))
}
biases = {
    'l1': tf.Variable(tf.constant(0.1, shape=[FLAGS.n_hidden_units])),
    'attention': tf.Variable(tf.constant(0.1, shape=[FLAGS.n_hidden_units])),
    # （n_classes）
    'out': tf.Variable(tf.constant(0.1, shape=[FLAGS.n_classes])),
}
add_weights = {
    'baseline': tf.Variable(tf.constant(0.25)),
    'position': tf.Variable(tf.constant(0.25)),
    'time': tf.Variable(tf.constant(0.25)),
    'event': tf.Variable(tf.constant(0.25))
}
# time_v = {
#     # 1: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 2: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 3: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 4: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     1: tf.Variable(tf.constant(0.1)),
#     2: tf.Variable(tf.constant(0.1)),
#     3: tf.Variable(tf.constant(0.1)),
#     4: tf.Variable(tf.constant(0.1))
# }

time_v = tf.get_variable('time', [4])
position = tf.get_variable('position', [5])

# position = {
#     # 0: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 1: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 2: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 3: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])),
#     # 4: tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units]))
#     0: tf.Variable(tf.constant(0.1)),
#     1: tf.Variable(tf.constant(0.1)),
#     2: tf.Variable(tf.constant(0.1)),
#     3: tf.Variable(tf.constant(0.1)),
#     4: tf.Variable(tf.constant(0.1))
# }

# event = list()
# for i in range(FLAGS.n_classes):
#     event_sub = list()
#     for j in range(FLAGS.n_classes):
#         event_sub.append(tf.Variable(tf.random_normal([FLAGS.n_hidden_units, FLAGS.n_hidden_units])))
#     event.append(event_sub)

event = tf.get_variable('event', [FLAGS.n_classes, FLAGS.n_classes])

baseline_gcn = list()
for _ in range(FLAGS.n_classes):
    baseline_gcn.append(tf.Variable(tf.random_normal([FLAGS.n_hidden_units +FLAGS.embedding_size, FLAGS.n_hidden_units])))

batchNum = 0
batch_xs = np.ones(shape=(FLAGS._batch_size, FLAGS.Chain_Lens*2)).astype(int)
batch_ys = np.ones(shape=(FLAGS._batch_size, FLAGS.Chain_Lens*2)).astype(int)


def next_batch():
    global batchNum, x_mat_list, y_tag_list
    if (batchNum + 1) * FLAGS._batch_size > x_mat_list.shape[0]:
        x_mat_list, y_tag_list = shuffle_xy(x_mat_list, y_tag_list)
        batchNum = 0
    batch_x = x_mat_list[batchNum * FLAGS._batch_size: (batchNum + 1) * FLAGS._batch_size]
    batch_y = y_tag_list[batchNum * FLAGS._batch_size: (batchNum + 1) * FLAGS._batch_size]
    batchNum += 1
    return batch_x, batch_y


def old_LSTM(X, weights, biases, beta):
    # hidden layer for input to cell

    embedding = tf.get_variable("embedding", [vocab_size, embedding_size], dtype=tf.float32)
    X_in = tf.nn.embedding_lookup(embedding, X[:, :Chain_Lens])
    # => (64 batch, 128 hidden)

    # cell
    fw_lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(n_hidden_units, forget_bias=1.0, state_is_tuple=True)
    fw_lstm_cell = tf.nn.rnn_cell.DropoutWrapper(fw_lstm_cell, output_keep_prob=output_kp)

    bw_lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(n_hidden_units, forget_bias=1.0, state_is_tuple=True)
    bw_lstm_cell = tf.nn.rnn_cell.DropoutWrapper(bw_lstm_cell, output_keep_prob=output_kp)

    fw_init_state = fw_lstm_cell.zero_state(_batch_size, dtype=tf.float32)
    bw_init_state = fw_lstm_cell.zero_state(_batch_size, dtype=tf.float32)
    outputs, states = tf.nn.bidirectional_dynamic_rnn(fw_lstm_cell, bw_lstm_cell, X_in,
            initial_state_fw=fw_init_state, initial_state_bw=bw_init_state, time_major=False)
    # outputs, states = tf.nn.dynamic_rnn(fw_lstm_cell, X_in, initial_state=fw_init_state, time_major=False)

    outputs = tf.add(outputs[0], outputs[1])
    results = tf.constant(0.1)
    # ********LSTM*******
    results = tf.add(results, tf.matmul(tf.add(states[0][1], states[1][1]), weights['out']) + biases['out'])
    # ********LSTM*******

    if trainType == 'position' or trainType == 'all':
        # ********position attention*******
        for i in range(5):
            # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
            result_beta = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, n_hidden_units])
            result_beta = tf.matmul(result_beta, beta[i]) + biases['beta']
            results = tf.add(results, result_beta)
        # ********position attention*******

    if trainType == 'time' or trainType == 'all':
        # ********time attention*******
        for i in range(Chain_Lens):
            # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
            result_alpha = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, n_hidden_units])
            result_sub = tf.constant(0.1, shape=[n_classes])
            for index in range(_batch_size):
                reshape_r_a = tf.reshape(result_alpha[index], [1, -1])
                result_sub = tf.concat([result_sub, tf.squeeze(tf.matmul(reshape_r_a, alpha[batch_xs[index][i+5]]) + biases['alpha'])], 0)
            # batch_number * n_classes
            result_sub = tf.reshape(result_sub[n_classes:], [_batch_size, n_classes])
            results = tf.add(results, result_sub)
        # ********time attention*******

    if trainType == 'event' or trainType == 'all':
        # ********event attention*******
        adjacency_mat = pickle.load(open('../data/adjacency.regular', 'rb'))

        assist_list = [i for i in range(5)]
        for i in range(Chain_Lens):
            # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
            result_event = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, n_hidden_units])
            result_sub = tf.constant(0.1, shape=[n_classes])
            for index in range(_batch_size):
                reshape_e = tf.reshape(result_event[index], [1, -1])
                assist_list.remove(i)
                event_sum = tf.constant(0.1, shape=[n_hidden_units, n_classes])
                for j in assist_list:
                    weight = adjacency_mat[batch_xs[index][i]][batch_xs[index][j]]
                    tf.add(event_sum, event[batch_xs[index][i]][batch_xs[index][j]] * weight)
                result_sub = tf.concat(
                    [result_sub, tf.squeeze(tf.matmul(reshape_e, event_sum) + biases['event'])],0)
                assist_list.append(i)
            # batch_number * n_classes
            result_sub = tf.reshape(result_sub[n_classes:], [_batch_size, n_classes])
            results = tf.add(results, result_sub)
        # ********event attention*******

    return results


# TODO 特征维度 concat instead of add   或者用 权重add ok
def LSTM(X, weights, biases, time_v, position, event):
    # hidden layer for input to cell

    embedding = tf.get_variable("embedding", [FLAGS.vocab_size, FLAGS.embedding_size], dtype=tf.float32)
    X_in = tf.nn.embedding_lookup(embedding, X[:, :FLAGS.Chain_Lens])
    # => (64 batch, 128 hidden)

    # cell
    def unit_lstm():
        fw_lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(FLAGS.n_hidden_units, forget_bias=1.0, state_is_tuple=True)
        fw_lstm_cell = tf.nn.rnn_cell.DropoutWrapper(fw_lstm_cell, output_keep_prob=output_kp)
        return fw_lstm_cell

    # bw_lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(FLAGS.n_hidden_units, forget_bias=1.0, state_is_tuple=True)
    # bw_lstm_cell = tf.nn.rnn_cell.DropoutWrapper(bw_lstm_cell, output_keep_prob=output_kp)

    fw_cell = tf.nn.rnn_cell.MultiRNNCell([unit_lstm() for i in range(3)], state_is_tuple=True)
    # bw_cell = tf.nn.rnn_cell.MultiRNNCell([bw_lstm_cell] * 3, state_is_tuple=True)

    fw_init_state = fw_cell.zero_state(FLAGS._batch_size, dtype=tf.float32)
    # bw_init_state = bw_cell.zero_state(FLAGS._batch_size, dtype=tf.float32)

    # outputs, states = tf.nn.bidirectional_dynamic_rnn(fw_cell, bw_cell, X_in, dtype=tf.float32,
    #         time_major=False)
    # initial_state_fw = fw_init_state, initial_state_bw = bw_init_state,
    outputs, states = tf.nn.dynamic_rnn(fw_cell, X_in, initial_state=fw_init_state, time_major=False)

    # ********LSTM*******
    # TODO 应该也取前面hidden states的平均值 ok
    # outputs = tf.add(outputs[0], outputs[1])
    ### tf_results = tf.concat([states[0][1], states[1][1]], 1)
    # tf_results = tf.add(states[0][1], states[1][1]) * add_weights['baseline']

    tf_results = tf.constant(0.0001)
    tf_baseline = tf.constant(0.0001)
    for i in range(FLAGS.Chain_Lens):
        # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
        result_beta = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, FLAGS.n_hidden_units])
        result_beta = result_beta * (1 / FLAGS.Chain_Lens)
        tf_baseline = tf.add(tf_baseline, result_beta)
    # tf_results = tf.add(tf_results, tf_baseline * (1-add_weights['position']-add_weights['time']-add_weights['event']))
    tf_results = tf.add(tf_results, tf_baseline)

    # tf_results = states[1]
    # ********LSTM*******

    if trainType == 'attention':
        # ********attention*******
        tf_attention = tf.constant(0.1, shape=[FLAGS._batch_size, 1])
        for i in range(FLAGS.Chain_Lens):
            result_beta = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, FLAGS.n_hidden_units])
            result_beta = tf.nn.tanh(tf.matmul(result_beta, weights['attention']) + biases['attention'])
            tf_attention = tf.concat([tf_attention, result_beta],1)
        tf_attention = tf.reshape(tf.slice(tf_attention, [0, 1], [-1,-1]), [FLAGS._batch_size, FLAGS.Chain_Lens, -1])

        tf_other = tf.constant(0.001, shape=[1])
        for i in range(FLAGS._batch_size):
            soft = tf.reshape(tf.nn.softmax(tf.squeeze(tf.matmul(tf_attention[i], weights['attention_2']))),[-1,1])
            tf_other = tf.concat([tf_other, tf.reshape(tf.matmul(tf.transpose(outputs[i]), soft), [-1])], 0)
        tf_other = tf.reshape(tf_other[1:], [FLAGS._batch_size, -1])
        # ********attention*******
        tf_results = tf.add(tf_results, tf_other)

    # TODO attention 换成数值试， 比较baseline和position
    if trainType == 'position' or trainType == 'all':
        # ********position attention*******
        tf_position = tf.constant(0.0001)
        for i in range(FLAGS.Chain_Lens):
            # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
            result_beta = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, FLAGS.n_hidden_units])
            # result_beta = tf.matmul(result_beta, position[i])
            result_beta = result_beta * position[i]
            tf_position = tf.add(tf_position, result_beta)
        # ********position attention*******
        # tf_results = tf.concat([tf_results, tf_position], 1)
        tf_results = tf.add(tf_results, tf_position*add_weights['position'])

    if trainType == 'time' or trainType == 'all':
        # ********time attention*******
        tf_time = tf.constant(0.0001)
        for i in range(FLAGS.Chain_Lens):
            # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
            result_alpha = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, FLAGS.n_hidden_units])
            result_sub = tf.constant(0.1, shape=[FLAGS.n_hidden_units])
            for index in range(FLAGS._batch_size):
                # reshape_r_a = tf.reshape(result_alpha[index], [1, -1])
                # result_sub = tf.concat([result_sub, tf.squeeze(tf.matmul(reshape_r_a, time_v[batch_xs[index][i+5]]))], 0)
                result_sub = tf.concat([result_sub, result_alpha[index] * time_v[X[index][i + 5]-1]], 0)
            # batch_number * n_hidden_units
            result_sub = tf.reshape(result_sub[FLAGS.n_hidden_units:], [FLAGS._batch_size, FLAGS.n_hidden_units])
            tf_time = tf.add(tf_time, result_sub)
        # ********time attention*******
        # tf_results = tf.concat([tf_results, tf_time], 1)
        tf_results = tf.add(tf_results, tf_time*add_weights['time'])

    # TODO self-attention 只考虑前面的事件 ok
    if trainType == 'event' or trainType == 'all':
        # ********event attention*******
        tf_event = tf.constant(0.0001)
        for i in range(FLAGS.Chain_Lens):
            # batch_number * Chain_Lens * n_hidden_units  =>  按某i个Chain_Lens取数据
            result_event = tf.reshape(tf.slice(outputs, [0, i, 0], [-1, 1, -1]), [-1, FLAGS.n_hidden_units])
            result_sub = tf.constant(0.0001, shape=[FLAGS.n_hidden_units])
            for index in range(FLAGS._batch_size):
                # reshape_e = tf.reshape(result_event[index], [1, -1])
                event_sum = tf.constant(0.0001)
                for j in range(i):
                    tf.add(event_sum, event[X[index][i]][X[index][j]])
                result_sub = tf.concat([result_sub, result_event[index] * event_sum],0)
            # batch_number * n_hidden_units
            result_sub = tf.reshape(result_sub[FLAGS.n_hidden_units:], [FLAGS._batch_size, FLAGS.n_hidden_units])
            tf_event = tf.add(tf_event, result_sub)
        # ********event attention*******
        # tf_results = tf.concat([tf_results, tf_event], 1)
        tf_results = tf.add(tf_results, tf_event*add_weights['event'])

    if classifier == 'mlp':
        # mlp classifer
        # mlp_l1 = tf.matmul(tf_results, weights[trainType]) + biases['l1']
        mlp_l1 = tf.matmul(tf_results, weights['weight_add']) + biases['l1']
        mlp_l2 = tf.nn.relu(mlp_l1)
        results = tf.matmul(mlp_l2, weights['out']) + biases['out']
        # mlp classifer

    # TODO labeling embedding 用上01矩阵  多层gcn
    # label embedding
    label_embedding = tf.nn.embedding_lookup(embedding, [i for i in range(FLAGS.n_classes)])

    # # TODO 邻接矩阵归一化 不要01形式 ok
    # adjacency_mat = pickle.load(open('../data/adjacency.regular', 'rb'))
    # hidden_label_em = tf.constant([0.1])
    #
    # # TODO 再乘一个W
    # for i in range(label_embedding.shape[0]):
    #     q = tf.constant(0.1, shape=[FLAGS.embedding_size])
    #     for j in range(label_embedding.shape[0]):
    #         if j == i:
    #             q = tf.add(q, label_embedding[j])
    #         else:
    #             q = tf.add(q, label_embedding[j] * adjacency_mat[i][j])
    #     hidden_label_em = tf.concat([hidden_label_em, q], 0)
    # hidden_label_em = tf.reshape(hidden_label_em[1:], [FLAGS.n_classes, FLAGS.embedding_size])
    # label embedding

    # TODO 最后的GCN MLP部分  大U 25*276  ok
    # TODO 拼接后进GCN  AxW
    if classifier == 'gcn':
        # gcn classifier
        tf_sequence = tf.reshape(tf.tile(tf_results, [1, FLAGS.n_classes]), [FLAGS._batch_size * FLAGS.n_classes, -1])
        tf_label = tf.tile(label_embedding, [FLAGS._batch_size, 1])
        tf_concat = tf.reshape(tf.concat([tf_sequence, tf_label], 1), [FLAGS._batch_size, FLAGS.n_classes, -1])
        # gcn_l1 = tf.reshape(tf.matmul(tf_concat, weights[trainType+'_gcn']),[_batch_size, n_classes, -1])+biases[trainType]

        # gcn_l1 = tf.constant(0.1, shape=[FLAGS._batch_size, 1])
        # for i in range(FLAGS.n_classes):
        #     gcn_beta = tf.reshape(tf.slice(tf_concat, [0, i, 0], [-1, 1, -1]), [FLAGS._batch_size, -1])
        #     gcn_beta = tf.matmul(gcn_beta, baseline_gcn[i])
        #     gcn_l1 = tf.concat([gcn_l1, gcn_beta], 1)
        # gcn_l1 = tf.reshape(tf.slice(gcn_l1, [0,1],[-1,-1]),[FLAGS._batch_size,FLAGS.n_classes,-1])

        adjacency_mat = pickle.load(open('../data/adjacency.data', 'rb'))
        myarray = np.zeros((25, 25), dtype='float32')
        for key1, row in adjacency_mat.items():
            for key2, value in row.items():
                myarray[key1, key2] = value
        X_scaled = preprocessing.scale(myarray)

        gcn_l1 = tf.constant(0.1, shape=[FLAGS.n_classes, FLAGS.n_hidden_units])
        for i in range(FLAGS._batch_size):
            gcn_beta = tf.matmul(tf.matmul(X_scaled, tf_concat[i]), weights['baseline_gcn']) + biases['l1']
            gcn_l1 = tf.concat([gcn_l1, gcn_beta], 0)
        gcn_l1 = tf.reshape(gcn_l1[FLAGS.n_classes:], shape=[FLAGS._batch_size, FLAGS.n_classes, -1])

        gcn_l2 = tf.nn.relu(gcn_l1)
        results = tf.reshape(tf.matmul(tf.reshape(gcn_l2, [FLAGS._batch_size*FLAGS.n_classes,-1]), weights['out_gcn']),
                             [FLAGS._batch_size, FLAGS.n_classes]) + biases['out']
        # gcn classifier
    return results


pred = LSTM(x, weights, biases, time_v, position, event)
cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=pred, labels=y))
# 预测结果
pred_y = tf.cast(tf.argmax(pred, 1), tf.int32)
train_op = tf.train.AdamOptimizer(FLAGS.lr).minimize(cost)


k = 10  # targets对应的索引是否在最大的前k个数据中
output = tf.nn.in_top_k(pred, tf.argmax(y, 1), k)
accuracy = tf.reduce_mean(tf.cast(output, tf.float32))

# correct_pred = tf.equal(tf.argmax(pred, 1), tf.argmax(y, 1))
# accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

init = tf.global_variables_initializer()
saver = tf.train.Saver(max_to_keep = 200)


def test_step(data_x, data_y):
    # data_x, data_y = shuffle_xy(data_x, data_y)
    data_y = np.reshape(data_y, [FLAGS._batch_size, -1])
    test_accuracy, test_cost, pred = sess.run([accuracy, cost, pred_y], feed_dict={
        x: data_x,
        y: data_y,
        output_kp: 1.0
    })
    # np.savetxt('../data/pred_y.txt', pred, fmt='%d')
    # data_y_actual = tf.cast(tf.argmax(data_y, 1), tf.int32).eval()
    # np.savetxt('../data/pred_y_actual.txt', data_y_actual, fmt='%d')

    return test_accuracy, test_cost


with tf.Session(config=config) as sess:
    # training
    sess.run(init)
    epoch_i = 0
    # 加载最后一个模型
    # saver.restore(sess, '../data/ckpt/{}{}_new.ckpt-{}'.format(trainType, classifier, 16002))

    print('***TRAINING PROCESS***')
    with open('train_result.txt', 'a') as file:
        file.write('\n{}__{}__{}__hidden_units:{}__lr:{}__batch:{}__embedding:{}__{}:\n'.format(trainType, classifier, note,
                    FLAGS.n_hidden_units, FLAGS.lr, FLAGS._batch_size, FLAGS.embedding_size, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))

        x_mat_list, y_tag_list = shuffle_xy(x_mat_list, y_tag_list)
        while epoch_i < FLAGS.epoch:
            step = 0
            cost_trend = []
            while step < training_iters:
                batch_xs, batch_ys = next_batch()
                batch_ys = np.reshape(batch_ys, [FLAGS._batch_size, -1])

                _, total_cost = sess.run([train_op, cost], feed_dict={
                    x: batch_xs,
                    y: batch_ys,
                    output_kp: 0.8
                })
                cost_trend.append(total_cost)
                if step % 1000 == 0:
                    train_accuracy = sess.run(accuracy, feed_dict={
                        x: batch_xs,
                        y: batch_ys,
                        output_kp: 0.8
                    })
                    print("{}_step = {}, total cost = {:.5f}, training accuracy = {:.5f}".format(time.strftime("%H:%M:%S", time.localtime()), step,total_cost.item(), train_accuracy.item()))
                    saver.save(sess, model_save_path, global_step=epoch_i+step)
                step += 1
            # saver.save(sess, model_save_path, global_step=epoch_i)
            epoch_i += 1
            # with open('cost_trend.txt', 'wb') as infile:
            #     pickle.dump(cost_trend, infile)

            # testing

            print ('***TRAINING RESULT***EPOCH={}***{}'.format(epoch_i, trainType))
            x_mat_list, y_tag_list = shuffle_xy(x_mat_list, y_tag_list)
            # !!!!!!!!!!!!!!!!!!!!!为什么有这两行？!!!!!!!!!!!!!!!!!!!!!!!
            # x_mat_list = x_mat_list[0:trainNum]
            # y_tag_list = y_tag_list[0:trainNum]
            step = 0
            test_accuracy, test_cost = 0.0, 0.0
            while step < (trainNum / FLAGS._batch_size):
                batch_xs, batch_ys = next_batch()
                batch_accuracy, batch_cost = test_step(batch_xs, batch_ys)
                test_accuracy += batch_accuracy
                test_cost += batch_cost
                step += 1
            test_accuracy /= step
            test_cost /= step
            print ("training instance = %d, total cost = %g, training accuracy = %g" % (trainNum, test_cost, test_accuracy))
            # file.write('***TRAINING RESULT***EPOCH='+str(epoch_i)+'\n')
            # file.write("training instance = %d, total cost = %g, training accuracy = %g" %
            #            (trainNum, test_cost, test_accuracy)+'\n')
            file.write("%g" % test_accuracy + '\n')
