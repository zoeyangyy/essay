#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
POS tagger for building a LSTM based POS tagging model.
https://github.com/rockingdingo/deepnlp/tree/master/deepnlp/pos
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals  # compatible with python3 unicode coding

import time
import numpy as np
import tensorflow as tf
import sys, os

pkg_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../deepnlp/
sys.path.append(pkg_path)
from tf_test import reader  # absolute import

# language option python command line: python pos_model.py en
lang = "zh" if len(sys.argv) == 1 else sys.argv[1]  # default zh
file_path = os.path.dirname(os.path.abspath(__file__))
data_path = os.path.join(file_path, "data", lang)  # path to find corpus vocab file
train_dir = os.path.join(file_path, "ckpt", lang)  # path to find model saved checkpoint file

flags = tf.flags
logging = tf.logging

flags.DEFINE_string("pos_lang", lang, "pos language option for model config")
flags.DEFINE_string("pos_data_path", data_path, "data_path")
flags.DEFINE_string("pos_train_dir", train_dir, "Training directory.")
flags.DEFINE_string("pos_scope_name", "pos_var_scope", "Define POS Tagging Variable Scope Name")

FLAGS = flags.FLAGS


def data_type():
    return tf.float32


class POSTagger(object):
    """The POS Tagger Model."""

    def __init__(self, is_training, config):
        self.batch_size = batch_size = config.batch_size
        self.num_steps = num_steps = config.num_steps
        self.is_training = is_training
        size = config.hidden_size
        vocab_size = config.vocab_size

        # Define input and target tensors
        self._input_data = tf.placeholder(tf.int32, [batch_size, num_steps])
        self._targets = tf.placeholder(tf.int32, [batch_size, num_steps])

        with tf.device("/cpu:0"):
            embedding = tf.get_variable("embedding", [vocab_size, size], dtype=data_type())
            inputs = tf.nn.embedding_lookup(embedding, self._input_data)

        if (config.bi_direction):  # BiLSTM
            self._cost, self._logits = _bilstm_model(inputs, self._targets, config)
        else:  # LSTM
            self._cost, self._logits, self._final_state, self._initial_state = _lstm_model(inputs, self._targets,
                                                                                           config)

        # Gradients and SGD update operation for training the model.
        self._lr = tf.Variable(0.0, trainable=False)
        tvars = tf.trainable_variables()
        grads, _ = tf.clip_by_global_norm(tf.gradients(self._cost, tvars), config.max_grad_norm)
        optimizer = tf.train.GradientDescentOptimizer(self._lr)  # vanila SGD
        self._train_op = optimizer.apply_gradients(
            zip(grads, tvars),
            global_step=tf.contrib.framework.get_or_create_global_step())

        self._new_lr = tf.placeholder(data_type(), shape=[], name="new_learning_rate")
        self._lr_update = tf.assign(self._lr, self._new_lr)
        self.saver = tf.train.Saver(tf.global_variables())

    def assign_lr(self, session, lr_value):
        session.run(self._lr_update, feed_dict={self._new_lr: lr_value})

    @property
    def input_data(self):
        return self._input_data

    @property
    def targets(self):
        return self._targets

    @property
    def cost(self):
        return self._cost

    @property
    def logits(self):
        return self._logits

    @property
    def lr(self):
        return self._lr

    @property
    def train_op(self):
        return self._train_op

    @property
    def accuracy(self):
        return self._accuracy


# pos model configuration, set target num, and input vocab_size
class LargeConfigChinese(object):
    """Large config."""
    init_scale = 0.04
    learning_rate = 0.5
    max_grad_norm = 10
    num_layers = 2
    num_steps = 30
    hidden_size = 128
    max_epoch = 5
    max_max_epoch = 55
    keep_prob = 1.0
    lr_decay = 1 / 1.15
    batch_size = 1  # single sample batch
    vocab_size = 50000
    target_num = 44  # POS tagging tag number for Chinese
    bi_direction = True  # LSTM or BiLSTM


class LargeConfigEnglish(object):
    """Large config for English"""
    init_scale = 0.04
    learning_rate = 0.5
    max_grad_norm = 10
    num_layers = 2
    num_steps = 30
    hidden_size = 128
    max_epoch = 5
    max_max_epoch = 55
    keep_prob = 1.0  # There is one dropout layer on input tensor also, don't set lower than 0.9
    lr_decay = 1 / 1.15
    batch_size = 1  # single sample batch
    vocab_size = 50000
    target_num = 81  # English: Brown Corpus tags
    bi_direction = True  # LSTM or BiLSTM


def get_config(lang):
    if (lang == 'zh'):
        return LargeConfigChinese()
    elif (lang == 'en'):
        return LargeConfigEnglish()
    # other lang options

    else:
        return None


def _lstm_model(inputs, targets, config):
    '''
    @Use BasicLSTMCell and MultiRNNCell class to build LSTM model,
    @return logits, cost and others
    '''
    batch_size = config.batch_size
    num_steps = config.num_steps
    num_layers = config.num_layers
    size = config.hidden_size
    vocab_size = config.vocab_size
    target_num = config.target_num  # target output number

    lstm_cell = tf.contrib.rnn.BasicLSTMCell(size, forget_bias=0.0, state_is_tuple=True)
    cell = tf.contrib.rnn.MultiRNNCell([lstm_cell] * config.num_layers, state_is_tuple=True)

    initial_state = cell.zero_state(batch_size, data_type())

    outputs = []  # outputs shape: list of tensor with shape [batch_size, size], length: time_step
    state = initial_state
    with tf.variable_scope("pos_lstm"):
        for time_step in range(num_steps):
            if time_step > 0: tf.get_variable_scope().reuse_variables()
            (cell_output, state) = cell(inputs[:, time_step, :], state)  # inputs[batch_size, time_step, hidden_size]
            outputs.append(cell_output)

    output = tf.reshape(tf.concat(outputs, 1), [-1, size])  # output shape [time_step, size]
    softmax_w = tf.get_variable("softmax_w", [size, target_num], dtype=data_type())
    softmax_b = tf.get_variable("softmax_b", [target_num], dtype=data_type())
    logits = tf.matmul(output, softmax_w) + softmax_b  # logits shape[time_step, target_num]

    loss = tf.nn.sparse_softmax_cross_entropy_with_logits(labels=tf.reshape(targets, [-1]), logits=logits)
    cost = tf.reduce_sum(loss) / batch_size  # loss [time_step]

    # adding extra statistics to monitor
    correct_prediction = tf.equal(tf.cast(tf.argmax(logits, 1), tf.int32), tf.reshape(targets, [-1]))
    accuracy = tf.reduce_mean(tf.cast(correct_prediction, "float"))
    return cost, logits, state, initial_state


def _bilstm_model(inputs, targets, config):
    '''
    @Use BasicLSTMCell, MultiRNNCell method to build LSTM model
    @return logits, cost and others
    '''
    batch_size = config.batch_size
    num_steps = config.num_steps
    num_layers = config.num_layers
    size = config.hidden_size
    vocab_size = config.vocab_size
    target_num = config.target_num  # target output number

    lstm_fw_cell = tf.contrib.rnn.BasicLSTMCell(size, forget_bias=0.0, state_is_tuple=True)
    lstm_bw_cell = tf.contrib.rnn.BasicLSTMCell(size, forget_bias=0.0, state_is_tuple=True)

    cell_fw = tf.contrib.rnn.MultiRNNCell([lstm_fw_cell] * num_layers, state_is_tuple=True)
    cell_bw = tf.contrib.rnn.MultiRNNCell([lstm_bw_cell] * num_layers, state_is_tuple=True)

    initial_state_fw = cell_fw.zero_state(batch_size, data_type())
    initial_state_bw = cell_bw.zero_state(batch_size, data_type())

    # Split to get a list of 'n_steps' tensors of shape (batch_size, n_input)
    inputs_list = [tf.squeeze(s, axis=1) for s in tf.split(value=inputs, num_or_size_splits=num_steps, axis=1)]

    with tf.variable_scope("pos_bilstm"):
        outputs, state_fw, state_bw = tf.contrib.rnn.static_bidirectional_rnn(
            cell_fw, cell_bw, inputs_list, initial_state_fw=initial_state_fw,
            initial_state_bw=initial_state_bw)

    # outputs is a length T list of output vectors, which is [batch_size, 2 * hidden_size]
    # [time][batch][cell_fw.output_size + cell_bw.output_size]

    output = tf.reshape(tf.concat(outputs, 1), [-1, size * 2])
    # output has size: [T, size * 2]

    softmax_w = tf.get_variable("softmax_w", [size * 2, target_num], dtype=data_type())
    softmax_b = tf.get_variable("softmax_b", [target_num], dtype=data_type())
    logits = tf.matmul(output, softmax_w) + softmax_b

    # adding extra statistics to monitor
    correct_prediction = tf.equal(tf.cast(tf.argmax(logits, 1), tf.int32), tf.reshape(targets, [-1]))
    accuracy = tf.reduce_mean(tf.cast(correct_prediction, "float"))
    loss = tf.nn.sparse_softmax_cross_entropy_with_logits(labels=tf.reshape(targets, [-1]), logits=logits)
    cost = tf.reduce_sum(loss) / batch_size  # loss [time_step]
    return cost, logits


def run_epoch(session, model, word_data, tag_data, eval_op, verbose=False):
    """Runs the model on the given data."""
    epoch_size = ((len(word_data) // model.batch_size) - 1) // model.num_steps

    start_time = time.time()
    costs = 0.0
    iters = 0

    for step, (x, y) in enumerate(reader.iterator(word_data, tag_data, model.batch_size,
                                                  model.num_steps)):
        fetches = [model.cost, model.logits, eval_op]  # eval_op define the m.train_op or m.eval_op
        feed_dict = {}
        feed_dict[model.input_data] = x
        feed_dict[model.targets] = y
        cost, logits, _ = session.run(fetches, feed_dict)
        costs += cost
        iters += model.num_steps

        if verbose and step % (epoch_size // 10) == 10:
            print("%.3f perplexity: %.3f speed: %.0f wps" %
                  (step * 1.0 / epoch_size, np.exp(costs / iters),
                   iters * model.batch_size / (time.time() - start_time)))

        # Save Model to CheckPoint when is_training is True
        if model.is_training:
            if step % (epoch_size // 10) == 10:
                checkpoint_path = os.path.join(FLAGS.pos_train_dir, "pos_bilstm.ckpt")
                model.saver.save(session, checkpoint_path)
                print("Model Saved... at time step " + str(step))

    return np.exp(costs / iters)


def main(_):
    if not FLAGS.pos_data_path:
        raise ValueError("No data files found in 'data_path' folder")

    raw_data = reader.load_data(FLAGS.pos_data_path)
    train_word, train_tag, dev_word, dev_tag, test_word, test_tag, vocabulary = raw_data

    config = get_config(FLAGS.pos_lang)
    eval_config = get_config(FLAGS.pos_lang)
    eval_config.batch_size = 1
    eval_config.num_steps = 1

    with tf.Graph().as_default(), tf.Session() as session:
        initializer = tf.random_uniform_initializer(-config.init_scale,
                                                    config.init_scale)
        with tf.variable_scope(FLAGS.pos_scope_name, reuse=None, initializer=initializer):
            m = POSTagger(is_training=True, config=config)
        with tf.variable_scope(FLAGS.pos_scope_name, reuse=True, initializer=initializer):
            mvalid = POSTagger(is_training=False, config=config)
            mtest = POSTagger(is_training=False, config=eval_config)

        # CheckPoint State
        ckpt = tf.train.get_checkpoint_state(FLAGS.pos_train_dir)
        if ckpt:
            print("Loading model parameters from %s" % ckpt.model_checkpoint_path)
            m.saver.restore(session, tf.train.latest_checkpoint(FLAGS.pos_train_dir))
        else:
            print("Created model with fresh parameters.")
            session.run(tf.global_variables_initializer())

        for i in range(config.max_max_epoch):
            lr_decay = config.lr_decay ** max(i - config.max_epoch, 0.0)
            m.assign_lr(session, config.learning_rate * lr_decay)

            print("Epoch: %d Learning rate: %.3f" % (i + 1, session.run(m.lr)))
            train_perplexity = run_epoch(session, m, train_word, train_tag, m.train_op,
                                         verbose=True)
            print("Epoch: %d Train Perplexity: %.3f" % (i + 1, train_perplexity))
            valid_perplexity = run_epoch(session, mvalid, dev_word, dev_tag, tf.no_op())
            print("Epoch: %d Valid Perplexity: %.3f" % (i + 1, valid_perplexity))

        test_perplexity = run_epoch(session, mtest, test_word, test_tag, tf.no_op())
        print("Test Perplexity: %.3f" % test_perplexity)


if __name__ == "__main__":
    tf.app.run()