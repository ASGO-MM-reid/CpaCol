r""" Implementation of center-pivot 4D convolution """
# Original code: HSNet (https://github.com/juhongm999/hsnet)

import torch
import torch.nn as nn
import math
class CenterPivotConv4d(nn.Module):
    r""" CenterPivot 4D conv"""
    def __init__(self, in_channels, out_channels, kernel_size, stride, padding, bias=True):
        super(CenterPivotConv4d, self).__init__()

        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size[:2], stride=stride[:2],
                               bias=bias, padding=padding[:2])
        self.conv2 = nn.Conv2d(in_channels, out_channels, kernel_size[2:], stride=stride[2:],
                               bias=bias, padding=padding[2:])

        self.stride34 = stride[2:]
        self.kernel_size = kernel_size
        self.stride = stride
        self.padding = padding
        self.idx_initialized = False
        self.idx_initialized_2 = False
        self.random_init()
    def prune(self, ct):
        bsz, ch, ha, wa, hb, wb = ct.size()
        idxh = torch.arange(start=0, end=hb, step=self.stride[2:][0], device=ct.device)
        idxw = torch.arange(start=0, end=wb, step=self.stride[2:][1], device=ct.device)
        self.len_h = len(idxh)
        self.len_w = len(idxw)
        self.idx = (idxw.repeat(self.len_h, 1) + idxh.repeat(self.len_w, 1).t() * wb).view(-1)
        self.idx_initialized = True
        ct_pruned = ct.view(bsz, ch, ha, wa, -1).index_select(4, self.idx).view(bsz, ch, ha, wa, self.len_h, self.len_w)

        return ct_pruned

    def prune_out2(self, ct):
        bsz, ch, ha, wa, hb, wb = ct.size()
        idxh = torch.arange(start=0, end=ha, step=self.stride[:2][0], device=ct.device)
        idxw = torch.arange(start=0, end=wa, step=self.stride[:2][1], device=ct.device)
        self.len_h = len(idxh)
        self.len_w = len(idxw)
        self.idx = (idxw.repeat(self.len_h, 1) + idxh.repeat(self.len_w, 1).t() * wa).view(-1)
        self.idx_initialized_2 = True
        ct_pruned = ct.view(bsz, ch, -1, hb, wb).permute(0,1,3,4,2).index_select(4, self.idx).permute(0,1,4,2,3).view(bsz, ch, self.len_h, self.len_w, hb, wb)

        return ct_pruned

    def forward(self, x):
        if self.stride[2:][-1] > 1:
            out1 = self.prune(x)
        else:
            out1 = x
        bsz, inch, ha, wa, hb, wb = out1.size()
        out1 = out1.permute(0, 4, 5, 1, 2, 3).contiguous().view(-1, inch, ha, wa)
        # print('conv4d, out1:', out1.shape)
        out1 = self.conv1(out1)
        outch, o_ha, o_wa = out1.size(-3), out1.size(-2), out1.size(-1)
        out1 = out1.view(bsz, hb, wb, outch, o_ha, o_wa).permute(0, 3, 4, 5, 1, 2).contiguous()


        if self.stride[:2][-1] > 1:
            out2 = self.prune_out2(x)
        else:
            out2 = x
        bsz, inch, ha, wa, hb, wb = out2.size()
        out2 = out2.permute(0, 2, 3, 1, 4, 5).contiguous().view(-1, inch, hb, wb)
        out2 = self.conv2(out2)
        outch, o_hb, o_wb = out2.size(-3), out2.size(-2), out2.size(-1)
        out2 = out2.view(bsz, ha, wa, outch, o_hb, o_wb).permute(0, 3, 1, 2, 4, 5).contiguous()
        if out1.size()[-2:] != out2.size()[-2:] and self.padding[-2:] == (0, 0):
            out1 = out1.view(bsz, outch, o_ha, o_wa, -1).sum(dim=-1)
            out2 = out2.squeeze()
        y = out1 + out2
        return y
        
    def random_init(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                nn.init.normal_(m.weight, 0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)
        