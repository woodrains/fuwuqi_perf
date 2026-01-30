import numpy as np

# Data set configuration.
data_set_dir = 'Data1/'
data_set_idx = 8
datasets = [
  (data_set_dir + '507.cactuBSSN_r.seq.mmap', 1011073),
  (data_set_dir + '508.namd_r.seq.mmap', 1079195),
  (data_set_dir + '519.lbm_r.seq.mmap', 1077935),
  (data_set_dir + '521.wrf_r.seq.mmap', 1058710),
  (data_set_dir + '500.perlbench_r.seq.mmap', 1158521),
  (data_set_dir + '502.gcc_r.seq.mmap', 15836),
  (data_set_dir + '505.mcf_r.seq.mmap', 1020646),
  (data_set_dir + '523.xalancbmk_r.seq.mmap', 376794),
  (data_set_dir + 'all.mmap', 6798710)
]

data_item_format = np.float32
# total batch number is 1,659.84
testbatchnum = 1580
validbatchnum = 1500
validbatchsize = 16

ori_batch_size = 4096
test_start = testbatchnum * ori_batch_size
test_end = (testbatchnum + 1) * ori_batch_size
valid_start = validbatchnum * ori_batch_size
valid_end = (validbatchnum + validbatchsize) * ori_batch_size

seq_length = 1024
input_length = 50
tgt_length = 12
input_start = 12
inst_length = input_start + input_length
