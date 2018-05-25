#!/usr/bin/env python
# -*- coding: utf-8 -*-


"""
    Build the LSTM(BLSTM)  neural networks for PIT speech separation.

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import time

import tensorflow as tf
from tensorflow.contrib.rnn.python.ops import rnn
import numpy as np

class LSTM(object):
    """Build BLSTM or LSTM model with PIT loss functions.
       If you use this module to train your module, make sure that 
       your prepare the right format data! 
 
    Attributes:
        config: Used to config our model
                config.input_size: feature (input) size;
                config.output_size: the final layer(output layer) size;
                config.rnn_size: the rnn cells' number
                config.batch_size: the batch_size for training
                config.rnn_num_layers: the rnn layers numbers
                config.keep_prob: the dropout rate
        inputs: the mixed speech feature without cmvn
        inputs_cmvn: the mixed speech feature with cmvn as the inputs of model(LSTM or BLSTM)
        labels1: the spk1's feature, as targets to train the model
        labels2: the spk2's feature, as targets to train the model
        infer: bool, if training(false) or test (true)
    """

    def __init__(self, config,  inputs, labels, lengths, costType=0,infer=False):
        self._inputs = inputs
        #self._mixed = inputs
        self._mixed = tf.slice(inputs, [0, 0, 1], [-1, -1, config.output_size])
        self._labels1 = tf.slice(labels, [0,0,0], [-1,-1, config.output_size])
        self._labels2 = tf.slice(labels, [0,0,config.output_size], [-1,-1, config.output_size])
        self._labels3 = tf.slice(labels, [0, 0, config.output_size*2], [-1, -1, config.output_size])
        self._labels4 = tf.slice(labels, [0, 0, config.output_size*3], [-1, -1, config.output_size])
        self._labels5 = tf.slice(labels, [0, 0, config.output_size*4], [-1, -1, -1])
        self._costType=tf.Variable(tf.constant(costType),trainable=False)
        self._lengths = lengths
        # self._genders = genders
        self._model_type = config.model_type

        outputs = self._inputs
        ## This first layer-- feed forward layer
        ## Transform the input to the right size before feed into RNN

        with tf.variable_scope('forward1'):
            outputs = tf.reshape(outputs, [-1, config.input_size])
            outputs = tf.layers.dense(outputs, units=config.rnn_size,
                                      activation=tf.nn.tanh,
                                      reuse=tf.get_variable_scope().reuse)
            outputs = tf.reshape(
                outputs, [config.batch_size,-1, config.rnn_size])
            print(outputs.shape)
        
        ## Configure the LSTM or BLSTM model 
        ## For BLSTM, we use the BasicLSTMCell.For LSTM, we use LSTMCell. 
        ## You can change them and test the performance...

        if config.model_type.lower() == 'blstm': 
            with tf.variable_scope('blstm'):
                #此处代码由get_cell完成
                # cell = tf.contrib.rnn.BasicLSTMCell(config.rnn_size)
                # if not infer and config.keep_prob < 1.0:
                #     cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=config.keep_prob)

                # lstm_fw_cell = tf.contrib.rnn.MultiRNNCell([cell] * config.rnn_num_layers)
                # lstm_bw_cell = tf.contrib.rnn.MultiRNNCell([cell] * config.rnn_num_layers)
                # 使用多层LSTM，不能用lstm_cell*NUM_LAYERS的方法，会导致LSTM的tensor名字都一样
                # cell = tf.contrib.rnn.MultiRNNCell([LstmCell() for _ in range(NUM_LAYERS)])
                lstm_fw_cell = tf.contrib.rnn.MultiRNNCell([self.get_cell(infer,config.rnn_size,config.keep_prob) for _ in range(config.rnn_num_layers)])
                lstm_bw_cell = tf.contrib.rnn.MultiRNNCell([self.get_cell(infer,config.rnn_size,config.keep_prob) for _ in range(config.rnn_num_layers)])
                lstm_fw_cell = _unpack_cell(lstm_fw_cell)
                lstm_bw_cell = _unpack_cell(lstm_bw_cell)
                result = rnn.stack_bidirectional_dynamic_rnn(
                    cells_fw = lstm_fw_cell,
                    cells_bw = lstm_bw_cell,
                    inputs=outputs,
                    dtype=tf.float32,
                    sequence_length=self._lengths)#sequence_length=Noneself._lengths
                outputs, fw_final_states, bw_final_states = result
        if config.model_type.lower() == 'lstm':
            with tf.variable_scope('lstm'):
                def lstm_cell():
                    return tf.contrib.rnn.LSTMCell(
                        config.rnn_size, forget_bias=1.0, use_peepholes=True,
                        initializer=tf.contrib.layers.xavier_initializer(),
                        state_is_tuple=True, activation=tf.tanh)
                attn_cell = lstm_cell
                if not infer and config.keep_prob < 1.0:
                    def attn_cell():
                        return tf.contrib.rnn.DropoutWrapper(lstm_cell(), output_keep_prob=config.keep_prob)
                cell = tf.contrib.rnn.MultiRNNCell(
                    [attn_cell() for _ in range(config.rnn_num_layers)],
                    state_is_tuple=True)
                self._initial_state = cell.zero_state(config.batch_size, tf.float32)
                state = self.initial_state
                outputs, state = tf.nn.dynamic_rnn(
                    cell, outputs,
                    dtype=tf.float32,
                    sequence_length=self._lengths,
                    initial_state=self.initial_state)
                self._final_state = state
        
        ## Feed forward layer. Transform the RNN output to the right output size

        with tf.variable_scope('forward2'):
            if self._model_type.lower() == 'blstm':
                outputs = tf.reshape(outputs, [-1, 2*config.rnn_size])
                in_size=2*config.rnn_size
            else:
                outputs = tf.reshape(outputs, [-1, config.rnn_size])
                in_size = config.rnn_size
            #w1,b1 =self. _weight_and_bias("L_1",in_size,256)
            #outputs1 = tf.nn.relu(tf.matmul(outputs,w1)+b1)
            #w2,b2 = self._weight_and_bias("L_2",256,256)
            #outputs2 = tf.nn.relu(tf.matmul(outputs1,w2)+b2+outputs1)
            out_size = config.output_size
            #in_size=256
            weights1 = tf.get_variable('weights1', [in_size, out_size],
            initializer=tf.random_normal_initializer(stddev=0.01))
            biases1 = tf.get_variable('biases1', [out_size],
            initializer=tf.constant_initializer(0.0))
            weights2 = tf.get_variable('weights2', [in_size, out_size],
            initializer=tf.random_normal_initializer(stddev=0.01))
            biases2 = tf.get_variable('biases2', [out_size],
            initializer=tf.constant_initializer(0.0))
            weights3 = tf.get_variable('weights3', [in_size, out_size],
                                       initializer=tf.random_normal_initializer(stddev=0.01))
            biases3 = tf.get_variable('biases3', [out_size],
                                      initializer=tf.constant_initializer(0.0))
            weights4 = tf.get_variable('weights4', [in_size, out_size],
                                       initializer=tf.random_normal_initializer(stddev=0.01))
            biases4 = tf.get_variable('biases4', [out_size],
                                      initializer=tf.constant_initializer(0.0))
            weights5 = tf.get_variable('weights5', [in_size, out_size],
                                       initializer=tf.random_normal_initializer(stddev=0.01))
            biases5 = tf.get_variable('biases5', [out_size],
                                      initializer=tf.constant_initializer(0.0))
            mask1 = tf.nn.relu(tf.matmul(outputs, weights1) + biases1)
            mask2 = tf.nn.relu(tf.matmul(outputs, weights2) + biases2)
            mask3 = tf.nn.relu(tf.matmul(outputs, weights3) + biases3)
            mask4 = tf.nn.relu(tf.matmul(outputs, weights4) + biases4)
            mask5 = tf.nn.relu(tf.matmul(outputs, weights5) + biases5)
            self._activations1 = tf.reshape(
                mask1, [config.batch_size, -1, config.output_size])
            self._activations2 = tf.reshape(
                mask2, [config.batch_size, -1, config.output_size])
            self._activations3 = tf.reshape(
                mask3, [config.batch_size, -1, config.output_size])
            self._activations4 = tf.reshape(
                mask4, [config.batch_size, -1, config.output_size])
            self._activations5 = tf.reshape(
                mask5, [config.batch_size, -1, config.output_size])
            # in general, config.czt_dim == 0; However, we found that if we concatenate
            # 128 dim chrip-z transform feats to FFT feats, we got better SDR performance
            # for the same gender case. 

            # so , if you don't use czt feats (just the fft feats), config.czt_dim=0
            self._cleaned1 = self._activations1*self._mixed#self._mixed
            self._cleaned2 = self._activations2*self._mixed
            self._cleaned3 = self._activations3 * self._mixed
            self._cleaned4 = self._activations4 * self._mixed
            self._cleaned5 = self._activations5 * self._mixed
        # Ability to save the model
        self.saver = tf.train.Saver(tf.trainable_variables(), max_to_keep=30)

        if infer: return
       
       
        # Compute loss(Mse)
        # cost1 = tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned1-self._labels1,2),1)
        #                        +tf.reduce_sum(tf.pow(self._cleaned2-self._labels2,2),1)
        #                         + tf.reduce_sum(tf.pow(self._cleaned3 - self._labels3, 2), 1)
        #                         + tf.reduce_sum(tf.pow(self._cleaned4 - self._labels4, 2), 1)
        #                         + tf.reduce_sum(tf.pow(self._cleaned5 - self._labels5, 2), 1)
        #                        ,1)

        #

        cost1_2 = tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned1-self._labels1,2),1)
                               +tf.reduce_sum(tf.pow(self._cleaned2-self._labels2,2),1)
                                + tf.reduce_sum(tf.pow(self._cleaned3 - self._labels3, 2), 1)
                                + tf.reduce_sum(tf.pow(self._cleaned4 - self._labels4, 2), 1)
                                + tf.reduce_sum(tf.pow(self._cleaned5 - self._labels5, 2), 1)
                               ,1)
        cost1_3 = tf.reduce_mean(tf.reduce_sum(tf.pow(self._mixed - self._cleaned1 - self._cleaned2- self._cleaned3 - self._cleaned4- self._cleaned5 , 2), 1), 1)
        #cost1 = cost1_1 + cost1_3
        if self._costType==0:
            #默认值，计算全部cost
            scaled_clean1 = tf.divide(
                tf.multiply(self._mixed, self._cleaned1 - tf.reshape(tf.reduce_min(self._cleaned1, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned1, 1) - tf.reduce_min(self._cleaned1, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean2 = tf.divide(
                tf.multiply(self._mixed, self._cleaned2 - tf.reshape(tf.reduce_min(self._cleaned2, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned2, 1) - tf.reduce_min(self._cleaned2, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean3 = tf.divide(
                tf.multiply(self._mixed, self._cleaned3 - tf.reshape(tf.reduce_min(self._cleaned3, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned3, 1) - tf.reduce_min(self._cleaned3, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean4 = tf.divide(
                tf.multiply(self._mixed, self._cleaned4 - tf.reshape(tf.reduce_min(self._cleaned4, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned4, 1) - tf.reduce_min(self._cleaned4, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean5 = tf.divide(
                tf.multiply(self._mixed, self._cleaned5 - tf.reshape(tf.reduce_min(self._cleaned5, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned5, 1) - tf.reduce_min(self._cleaned5, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label1 = tf.divide(
                tf.multiply(self._mixed, self._labels1 - tf.reshape(tf.reduce_min(self._labels1, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels1, 1) - tf.reduce_min(self._labels1, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label2 = tf.divide(
                tf.multiply(self._mixed, self._labels2 - tf.reshape(tf.reduce_min(self._labels2, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels2, 1) - tf.reduce_min(self._labels2, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label3 = tf.divide(
                tf.multiply(self._mixed, self._labels3 - tf.reshape(tf.reduce_min(self._labels3, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels3, 1) - tf.reduce_min(self._labels3, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label4 = tf.divide(
                tf.multiply(self._mixed, self._labels4 - tf.reshape(tf.reduce_min(self._labels4, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels4, 1) - tf.reduce_min(self._labels4, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label5 = tf.divide(
                tf.multiply(self._mixed, self._labels5 - tf.reshape(tf.reduce_min(self._labels5, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels5, 1) - tf.reduce_min(self._labels5, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            cost1_1 = tf.reduce_mean(tf.reduce_sum(tf.pow(scaled_clean1 - scaled_label1, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean2 - scaled_label2, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean3 - scaled_label3, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean4 - scaled_label4, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean5 - scaled_label5, 2), 1)
                                     , 1)
            cost1=cost1_1+cost1_2+cost1_3
        elif self._costType==1 :
            scaled_clean1 = tf.divide(
                tf.multiply(self._mixed, self._cleaned1 - tf.reshape(tf.reduce_min(self._cleaned1, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned1, 1) - tf.reduce_min(self._cleaned1, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean2 = tf.divide(
                tf.multiply(self._mixed, self._cleaned2 - tf.reshape(tf.reduce_min(self._cleaned2, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned2, 1) - tf.reduce_min(self._cleaned2, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean3 = tf.divide(
                tf.multiply(self._mixed, self._cleaned3 - tf.reshape(tf.reduce_min(self._cleaned3, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned3, 1) - tf.reduce_min(self._cleaned3, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean4 = tf.divide(
                tf.multiply(self._mixed, self._cleaned4 - tf.reshape(tf.reduce_min(self._cleaned4, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned4, 1) - tf.reduce_min(self._cleaned4, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_clean5 = tf.divide(
                tf.multiply(self._mixed, self._cleaned5 - tf.reshape(tf.reduce_min(self._cleaned5, 1),
                                                                     [config.batch_size, -1, config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._cleaned5, 1) - tf.reduce_min(self._cleaned5, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label1 = tf.divide(
                tf.multiply(self._mixed, self._labels1 - tf.reshape(tf.reduce_min(self._labels1, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels1, 1) - tf.reduce_min(self._labels1, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label2 = tf.divide(
                tf.multiply(self._mixed, self._labels2 - tf.reshape(tf.reduce_min(self._labels2, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels2, 1) - tf.reduce_min(self._labels2, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label3 = tf.divide(
                tf.multiply(self._mixed, self._labels3 - tf.reshape(tf.reduce_min(self._labels3, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels3, 1) - tf.reduce_min(self._labels3, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label4 = tf.divide(
                tf.multiply(self._mixed, self._labels4 - tf.reshape(tf.reduce_min(self._labels4, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels4, 1) - tf.reduce_min(self._labels4, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            scaled_label5 = tf.divide(
                tf.multiply(self._mixed, self._labels5 - tf.reshape(tf.reduce_min(self._labels5, 1),
                                                                    [config.batch_size, -1,
                                                                     config.output_size])),
                tf.reshape(
                    tf.reduce_max(self._labels5, 1) - tf.reduce_min(self._labels5, 1) + tf.ones(
                        [config.batch_size, config.output_size]),
                    [config.batch_size, -1, config.output_size]))
            cost1_1 = tf.reduce_mean(tf.reduce_sum(tf.pow(scaled_clean1 - scaled_label1, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean2 - scaled_label2, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean3 - scaled_label3, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean4 - scaled_label4, 2), 1)
                                     + tf.reduce_sum(tf.pow(scaled_clean5 - scaled_label5, 2), 1)
                                     , 1)
            cost1=cost1_1
        elif self._costType==2 :
            cost1=tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned1-self._labels1,2),1),1)
        elif self._costType==3 :
            cost1=tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned2-self._labels2,2),1),1)
        elif self._costType == 4:
            cost1 = tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned3-self._labels3,2),1),1)
        elif self._costType == 5:
            cost1 = tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned4-self._labels4,2),1),1)
        elif self._costType == 6:
            cost1 = tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned5-self._labels5,2),1),1)
        else :
            cost1 = cost1_3

        # if self._costType!=0:
        #     self._costType=(self._costType+1)%7
        #     if self._costType==0:
        #         self._costType += 1
        cost2 = cost1
        # cost2 = tf.reduce_mean( tf.reduce_sum(tf.pow(self._cleaned2-self._labels1,2),1)
        #                        +tf.reduce_sum(tf.pow(self._cleaned1-self._labels2,2),1)
        #                        ,1)
        #
        idx = tf.cast(cost1>cost2,tf.float32)
        self._loss = tf.reduce_sum(idx*cost2+(1-idx)*cost1)
        self._loss = tf.reduce_sum(cost1)
        if tf.get_variable_scope().reuse: return

        self._lr = tf.Variable(0.0, trainable=False)
        tvars = tf.trainable_variables()
        grads, _ = tf.clip_by_global_norm(tf.gradients(self.loss, tvars),
                                          config.max_grad_norm)
        optimizer = tf.train.AdamOptimizer(self.lr)
        #optimizer = tf.train.GradientDescentOptimizer(self.lr)
        self._train_op = optimizer.apply_gradients(zip(grads, tvars))

        self._new_lr = tf.placeholder(
            tf.float32, shape=[], name='new_learning_rate')
        self._lr_update = tf.assign(self._lr, self._new_lr)

    def get_cell(self,infer,runSize,keepProb):
        cell = tf.contrib.rnn.BasicLSTMCell(runSize)
        if not infer and keepProb < 1.0:
            cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=keepProb)
        return cell

    def assign_lr(self, session, lr_value):
        session.run(self._lr_update, feed_dict={self._new_lr: lr_value})
    def get_opt_output(self):
        '''
            This function is just for the PIT testing with optimal assignment
        '''
        cost1 = tf.reduce_sum(tf.pow(tf.pow(self._cleaned1 - self._labels1, 2), 2)
                               + tf.pow(tf.pow(self._cleaned2 - self._labels2, 2), 2)
                               + tf.pow(tf.pow(self._cleaned3 - self._labels3, 2), 2)
                               + tf.pow(tf.pow(self._cleaned4 - self._labels4, 2), 2)
                               + tf.pow(tf.pow(self._cleaned5 - self._labels5, 2), 2)
                               , 1)
        cost2 = cost1
        # cost1 = tf.reduce_sum(tf.pow(self._cleaned1-self._labels1,2),2)+tf.reduce_sum(tf.pow(self._cleaned2-self._labels2,2),2)
        # cost2 = tf.reduce_sum(tf.pow(self._cleaned2-self._labels1,2),2)+tf.reduce_sum(tf.pow(self._cleaned1-self._labels2,2),2)
        idx = tf.slice(cost1, [0, 0], [1, -1]) > tf.slice(cost2, [0, 0], [1, -1])
        idx = tf.cast(idx, tf.float32)
        idx = tf.reduce_mean(idx,reduction_indices=0)
        idx = tf.reshape(idx, [tf.shape(idx)[0], 1])	
        x1 = self._cleaned1[0,:,:] * (1-idx) + self._cleaned2[0,:, :]*idx
        x2 = self._cleaned1[0,:,:]*idx + self._cleaned2[0,:,:]*(1-idx)
        row = tf.shape(x1)[0]
        col = tf.shape(x1)[1]
        x1 = tf.reshape(x1, [1, row, col])
        x2 = tf.reshape(x2, [1, row, col])
        return x1, x2
       
    @property
    def inputs(self):
        return self._inputs

    @property
    def labels(self):
        return self._labels1,self._labels2,self._labels3,self._labels4,self._labels5

    @property
    def initial_state(self):
        return self._initial_state

    @property
    def final_state(self):
        return self._final_state

    @property
    def lr(self):
        return self._lr

    @property
    def costType(self):
        return self._costType

    @property
    def activations(self):
        return self._activations

    @property
    def loss(self):
        return self._loss

    @property
    def train_op(self):
        return self._train_op

    @staticmethod
    def _weight_and_bias(name,in_size, out_size):
        # Create variable named "weights".
        weights = tf.get_variable(name+"_w", [in_size, out_size],
            initializer=tf.random_normal_initializer(stddev=0.01))
        # Create variabel named "biases".
        biases = tf.get_variable(name+"_b", [out_size],
            initializer=tf.constant_initializer(0.0))
        return weights, biases
def _unpack_cell(cell):
    if isinstance(cell,tf.contrib.rnn.MultiRNNCell):
        return cell._cells
    else:
        return [cell]
