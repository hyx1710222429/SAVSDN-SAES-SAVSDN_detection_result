import torch.nn as nn
import torch 
import torch.nn.functional as F
import numpy as np
import os
import sys
import math
import cv2 as cv
    
class ConvLSTMCell(nn.Module):
    def __init__(self, input_dim, hidden_dim, kernel_size, bias):
        """
        Initialize ConvLSTM cell.
        Parameters
        ----------
        input_dim: int
            Number of channels of input tensor.
        hidden_dim: int
            Number of channels of hidden state.
        kernel_size: (int, int)
            Size of the convolutional kernel.
        bias: bool
            Whether or not to add the bias.
        """
        super(ConvLSTMCell, self).__init__()

        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        self.kernel_size = kernel_size
        self.padding = kernel_size[0] // 2, kernel_size[1] // 2
        self.bias = bias

        self.conv = nn.Conv2d(in_channels=self.input_dim + self.hidden_dim,
                              out_channels=4 * self.hidden_dim,
                              kernel_size=self.kernel_size,
                              padding=self.padding,
                              bias=self.bias)

    def forward(self, input_tensor, cur_state):
        h_cur, c_cur = cur_state

        combined = torch.cat([input_tensor, h_cur], dim=1)  # concatenate along channel axis

        combined_conv = self.conv(combined)
        cc_i, cc_f, cc_o, cc_g = torch.split(combined_conv, self.hidden_dim, dim=1)
        i = torch.sigmoid(cc_i)
        f = torch.sigmoid(cc_f)
        o = torch.sigmoid(cc_o)
        g = torch.tanh(cc_g)

        c_next = f * c_cur + i * g
        h_next = o * torch.tanh(c_next)

        return h_next, c_next

    def init_hidden(self, batch_size, image_size):
        height, width = image_size
        
        return (torch.zeros(batch_size, self.hidden_dim, height, width, device=self.conv.weight.device),
                torch.zeros(batch_size, self.hidden_dim, height, width, device=self.conv.weight.device))
                

class ConvLSTM(nn.Module):
    """
    Parameters:
        input_dim: Number of channels in input
        hidden_dim: Number of hidden channels
        kernel_size: Size of kernel in convolutions
        num_layers: Number of LSTM layers stacked on each other
        batch_first: Whether or not dimension 0 is the batch or not
        bias: Bias or no bias in Convolution
        return_all_layers: Return the list of computations for all layers
        Note: Will do same padding.
    Input:
        A tensor of size B, T, C, H, W or T, B, C, H, W
    Output:
        A tuple of two lists of length num_layers (or length 1 if return_all_layers is False).
            0 - layer_output_list is the list of lists of length T of each output
            1 - last_state_list is the list of last states
                    each element of the list is a tuple (h, c) for hidden state and memory
    Example:
        >> x = torch.rand((32, 10, 64, 128, 128))
        >> convlstm = ConvLSTM(64, 16, 3, 1, True, True, False)
        >> _, last_states = convlstm(x)
        >> h = last_states[0][0]  # 0 for layer index, 0 for h index
    """
    def __init__(self, input_dim, hidden_dim, kernel_size, num_layers,
                 batch_first=True, bias=True, return_all_layers=False):
        super(ConvLSTM, self).__init__()

        self._check_kernel_size_consistency(kernel_size)

        # Make sure that both `kernel_size` and `hidden_dim` are lists having len == num_layers
        kernel_size = self._extend_for_multilayer(kernel_size, num_layers)
        hidden_dim = self._extend_for_multilayer(hidden_dim, num_layers)
        if not len(kernel_size) == len(hidden_dim) == num_layers:
            raise ValueError('Inconsistent list length.')

        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.kernel_size = kernel_size
        self.num_layers = num_layers
        self.batch_first = batch_first
        self.bias = bias
        self.return_all_layers = return_all_layers

        cell_list = []
        for i in range(0, self.num_layers):
            cur_input_dim = self.input_dim if i == 0 else self.hidden_dim[i - 1]

            cell_list.append(ConvLSTMCell(input_dim=cur_input_dim,
                                          hidden_dim=self.hidden_dim[i],
                                          kernel_size=self.kernel_size[i],
                                          bias=self.bias))

        self.cell_list = nn.ModuleList(cell_list)

    def forward(self, input_tensor, hidden_state=None):
        """
        Parameters
        ----------
        input_tensor: todo
            5-D Tensor either of shape (t, b, c, h, w) or (b, t, c, h, w)
        hidden_state: todo
            None. todo implement stateful
        Returns
        -------
        last_state_list, layer_output
        """
        if not self.batch_first:
            # (t, b, c, h, w) -> (b, t, c, h, w)
            input_tensor = input_tensor.permute(1, 0, 2, 3, 4)

        b, _, _, h, w = input_tensor.size()

        # Implement stateful ConvLSTM
        if hidden_state is None:#h,c=hidden_state[layer_idx] convLSTM有几层就有几组h,c初始状态 一层convLSTM有一个convLSTM cell 而hidden_state本身是一个tuple其第一个元素为h tensor 第二个元素为c tensor 这两个tensor的形状均为B C H W 即hidden_state=(tensor1,tensor2) tensor1.shape=B C H W
            # Since the init is done in forward. Can send image size here
            hidden_state = self._init_hidden(batch_size=b,
                                             image_size=(h, w))
                                             
                     

        layer_output_list = []
        last_state_list = []

        seq_len = input_tensor.size(1)
        cur_layer_input = input_tensor

        for layer_idx in range(self.num_layers):

            h, c = hidden_state[layer_idx]
            output_inner = []
            for t in range(seq_len):
                h, c = self.cell_list[layer_idx](input_tensor=cur_layer_input[:, t, :, :, :],
                                                 cur_state=[h, c])
                output_inner.append(h)

            layer_output = torch.stack(output_inner, dim=1)
            cur_layer_input = layer_output

            layer_output_list.append(layer_output)
            last_state_list.append([h, c])

        if not self.return_all_layers:
            layer_output_list = layer_output_list[-1:]
            last_state_list = last_state_list[-1:]

        return last_state_list

    def _init_hidden(self, batch_size, image_size):
        init_states = []
        for i in range(self.num_layers):
            init_states.append(self.cell_list[i].init_hidden(batch_size, image_size))
        return init_states

    @staticmethod
    def _check_kernel_size_consistency(kernel_size):
        if not (isinstance(kernel_size, tuple) or
                (isinstance(kernel_size, list) and all([isinstance(elem, tuple) for elem in kernel_size]))):
            raise ValueError('`kernel_size` must be tuple or list of tuples')

    @staticmethod
    def _extend_for_multilayer(param, num_layers):
        if not isinstance(param, list):
            param = [param] * num_layers
        return param
          
class LongShortTimeAutoEncodeDecoder(nn.Module):
    def __init__(
                self,
            ):
        super(LongShortTimeAutoEncodeDecoder, self).__init__() 

        #Motion Aware Block    
        self.convLstmMotionAwareBlock = ConvLSTM(3, 3, (3,3), 1, True, True, False)

        #Motion Pred Block
        self.convLstmMotionPredBlock = ConvLSTM(3, 3, (3,3), 1, True, True, False)
        
        #Decode
        self.convLstmDecode = ConvLSTM(3, 3, (3,3), 1, True, True, False)
        
    def forward(self,inputs9):  
        #运动编码：convLSTM对4个3帧分别进行运动编码
        inputs13=torch.transpose(inputs9[:,:,0:3,:,:], 1,2)#B C T H W --> B T C H W #1 2 3<-->0 1 2
        inputs35=torch.transpose(inputs9[:,:,2:5,:,:], 1,2)#B C T H W --> B T C H W #3 4 5<-->2 3 4
        inputs57=torch.transpose(inputs9[:,:,4:7,:,:], 1,2)#B C T H W --> B T C H W #5 6 7<-->4 5 6
        inputs79=torch.transpose(inputs9[:,:,6:9,:,:], 1,2)#B C T H W --> B T C H W #7 8 9<-->6 7 8
        inputs13355779=torch.cat([inputs13,inputs35],0)#B T C H W 1 3 3 512 512 --> B T C H W 4 3 3 512 512
        inputs13355779=torch.cat([inputs13355779,inputs57],0)
        inputs13355779=torch.cat([inputs13355779,inputs79],0)
        
        c13355779=self.convLstmMotionAwareBlock(inputs13355779)[0][1]#B C H W 4 3 512 512
        #场景编码:
        c133557=c13355779[0:3,:,:,:]#B C H W 3 3 512 512
        c133557=torch.unsqueeze(c133557,0)#B C H W 3 3 512 512 --> B T C H W 1 3 3 512 512 
        
        c79Pred=self.convLstmMotionPredBlock(c133557)[0][1]#cPred #B C H W
        #火星分割解码：将场景编码作为convLSTM的ct-1状态，7~9帧运动编码作为convLSTM的x输入，输出ht状态作为火星分割解码 后续可送入YOLOv5再次筛选火星分割结果
        c79=c13355779[3,:,:,:]#C H W 3 512 512
        cReal=torch.unsqueeze(c79,0)#C H W-->T C H W
        cReal=torch.unsqueeze(cReal,0)#B C H W-->B T C H W 1 1 3 512 512 
        convLSTMDecodeStateInit=[(torch.zeros(c79Pred.shape[0], c79Pred.shape[1], c79Pred.shape[2], c79Pred.shape[3], device=c79Pred.device),c79Pred)]
        
        h=self.convLstmDecode(cReal,convLSTMDecodeStateInit)[0][0]#B C H W

        return h
