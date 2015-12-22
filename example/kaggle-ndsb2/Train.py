
# coding: utf-8

# In[1]:

import os
import csv
import sys
import numpy as np
import mxnet as mx
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


# In[2]:

nframe = 30
noutput = 600
def get_lenet():
    source = mx.sym.Variable("data")
    source = (source - 128) * (1.0/128)
    frames = mx.sym.SliceChannel(source, num_outputs=30)
    diffs = [frames[i+1] - frames[i] for i in range(29)]
    source = mx.sym.Concat(*diffs)
    net = mx.sym.Convolution(source, kernel=(5, 5), num_filter=40)
    net = mx.sym.BatchNorm(net, fix_gamma=True)
    net = mx.sym.Activation(net, act_type="relu")
    net = mx.sym.Pooling(net, pool_type="max", kernel=(2,2), stride=(2,2))
    net = mx.sym.Convolution(net, kernel=(3, 3), num_filter=40)
    net = mx.sym.BatchNorm(net, fix_gamma=True)
    net = mx.sym.Activation(net, act_type="relu")
    net = mx.sym.Pooling(net, pool_type="max", kernel=(2,2), stride=(2,2))
    # first fullc
    flatten = mx.symbol.Flatten(net)
    flatten = mx.symbol.Dropout(flatten)
    fc1 = mx.symbol.FullyConnected(data=flatten, num_hidden=600)
    return mx.symbol.LogisticRegressionOutput(data=fc1, name='softmax')

def CRPS(label, pred):
    for i in range(pred.shape[0]):
        for j in range(pred.shape[1] - 1):
            if pred[i, j] > pred[i, j + 1]:
                pred[i, j + 1] = pred[i, j]
    return np.sum(np.square(label - pred)) / label.size


# In[3]:

def encode_label(label_data):
    stytole = label_data[:, 1]
    diastole = label_data[:, 2]
    stytole_encode = np.array([
            (x < np.arange(600)) for x in stytole
        ], dtype=np.uint8)
    diastole_encode = np.array([
            (x < np.arange(600)) for x in diastole
        ], dtype=np.uint8)
    return stytole_encode, diastole_encode

def encode_csv(label_csv, stytole_csv, diastole_csv):
    stytole_encode, diastole_encode = encode_label(np.loadtxt(label_csv, delimiter=","))
    np.savetxt(stytole_csv, stytole_encode, delimiter=",", fmt="%g")
    np.savetxt(diastole_csv, diastole_encode, delimiter=",", fmt="%g")

encode_csv("./train-label.csv", "./train-stytole.csv", "./train-diastole.csv")


# # Training the stytole net

# In[4]:

network = get_lenet()
batch_size = 32
devs = [mx.gpu(0)]
data_train = mx.io.CSVIter(data_csv="./train-64x64-data.csv", data_shape=(30, 64, 64),
                           label_csv="./train-stytole.csv", label_shape=(600,),
                           batch_size=batch_size)

data_validate = mx.io.CSVIter(data_csv="./validate-64x64-data.csv", data_shape=(30, 64, 64),
                              batch_size=1)

stytole_model = mx.model.FeedForward(ctx=devs,
        symbol             = network,
        num_epoch          = 65,
        learning_rate      = 0.001,
        wd                 = 0.00001,
        momentum           = 0.9)

stytole_model.fit(X=data_train, eval_metric = mx.metric.np(CRPS))


# # Predict stytole

# In[5]:

stytole_prob = stytole_model.predict(data_validate)


# # Training the diastole net

# In[6]:

network = get_lenet()
batch_size = 32
devs = [mx.gpu(0)]
data_train = mx.io.CSVIter(data_csv="./train-64x64-data.csv", data_shape=(30, 64, 64),
                           label_csv="./train-diastole.csv", label_shape=(600,),
                           batch_size=batch_size)

diastole_model = mx.model.FeedForward(ctx=devs,
        symbol             = network,
        num_epoch          = 65,
        learning_rate      = 0.001,
        wd                 = 0.00001,
        momentum           = 0.9)

diastole_model.fit(X=data_train, eval_metric = mx.metric.np(CRPS))


# # Predict diastole

# In[7]:

diastole_prob = diastole_model.predict(data_validate)


# # Generate Submission

# In[8]:

def accumulate_result(validate_lst, prob):
    sum_result = {}
    cnt_result = {}
    size = prob.shape[0]
    fi = csv.reader(open(validate_lst))
    for i in range(size):
        line = fi.__next__() # Python2: line = fi.next()
        idx = int(line[0])
        if idx not in cnt_result:
            cnt_result[idx] = 0.
            sum_result[idx] = np.zeros((1, prob.shape[1]))
        cnt_result[idx] += 1
        sum_result[idx] += prob[i, :]
    for i in cnt_result.keys():
        sum_result[i][:] /= cnt_result[i]
    return sum_result


# In[9]:

stytole_result = accumulate_result("./validate-label.csv", stytole_prob)
diastole_result = accumulate_result("./validate-label.csv", diastole_prob)


# In[10]:

# we have 2 person missing due to frame selection, use udibr's hist result instead
def doHist(data):
    h = np.zeros(600)
    for j in np.ceil(data).astype(int):
        h[j:] += 1
    h /= len(data)
    return h
train_csv = np.genfromtxt("./train-label.csv", delimiter=',')
hSystole = doHist(train_csv[:, 1])
hDiastole = doHist(train_csv[:, 2])


# In[11]:

def submission_helper(pred):
    p = np.zeros(600)
    pred.resize(p.shape)
    p[0] = pred[0]
    for j in range(1, 600):
        a = p[j - 1]
        b = pred[j]
        if b < a:
            p[j] = a
        else:
            p[j] = b
    return p



# In[12]:

fi = csv.reader(open("data/sample_submission_validate.csv"))
f = open("submission.csv", "w")
fo = csv.writer(f, lineterminator='\n')
fo.writerow(fi.__next__())
for line in fi:
    idx = line[0]
    key, target = idx.split('_')
    key = int(key)
    out = [idx]
    if key in stytole_result:
        if target == 'Diastole':
            out.extend(list(submission_helper(diastole_result[key])))
        else:
            out.extend(list(submission_helper(stytole_result[key])))
    else:
        print("Miss: %s" % idx)
        if target == 'Diastole':
            out.extend(hDiastole)
        else:
            out.extend(hSystole)
    fo.writerow(out)
f.close()


# In[ ]:



