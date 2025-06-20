import torch
import torch.nn as nn
import torch.nn.functional as F

from .conv4d import CenterPivotConv4d as Conv4d

def weights_init_kaiming(m):
    classname = m.__class__.__name__
    if classname.find('Linear') != -1:
        nn.init.normal_(m.weight, 0, 0.01)
        if m.bias is not None:
            nn.init.constant_(m.bias, 0.0)
    elif classname.find('Conv') != -1:
        nn.init.kaiming_normal_(m.weight, mode='fan_out')
        if m.bias is not None:
            nn.init.constant_(m.bias, 0.0)
    elif classname.find('BatchNorm') != -1:
        if m.affine:
            nn.init.constant_(m.weight, 1.0)
            nn.init.constant_(m.bias, 0.0)
            
            
            
class Cor_Learner(nn.Module):
    def __init__(self, inch = [0, 9]):
        super(Cor_Learner, self).__init__()

        def make_building_block(in_channel, out_channels, kernel_sizes, query_strides, key_strides, group=4):
            assert len(out_channels) == len(kernel_sizes) == len(key_strides)

            building_block_layers = []
            for idx, (outch, ksz, query_stride, key_stride) in enumerate(zip(out_channels, kernel_sizes, query_strides, key_strides)):
                inch = in_channel if idx == 0 else out_channels[idx - 1]
                ksz4d = (ksz,) * 4
                str4d = (query_stride,) * 2 + (key_stride,) * 2
                pad4d = (ksz // 2,) * 4

                building_block_layers.append(Conv4d(inch, outch, ksz4d, str4d, pad4d))
                building_block_layers.append(nn.GroupNorm(group, outch))
                building_block_layers.append(nn.ReLU(inplace=True))

            return nn.Sequential(*building_block_layers)

        outch1, outch2, outch3, outch4 = 16, 32, 64, 128
        # outch1, outch2, outch3, outch4 = 8, 16, 32, 64
        self.block1 = make_building_block(inch[1], [outch1], [5], [2], [2])
        self.block2 = make_building_block(outch1, [outch1, outch2], [3, 3], [1, 2], [1, 2])
        self.block3 = make_building_block(outch2, [outch2, outch2, outch3], [3, 3, 3], [1, 1, 2], [1, 1, 2])
        self.block4 = make_building_block(outch3, [outch3, outch3, outch4], [3, 3, 3], [1, 1, 1], [1, 1, 1])

        self.mlp = nn.Sequential(nn.Linear(outch4, outch4), nn.ReLU(), nn.Linear(outch4, 1))

        weight = torch.load('./weight.pt').unsqueeze(1).unsqueeze(3).repeat(1,11,1,11).unsqueeze(0).unsqueeze(0)
        self.dist = torch.nn.Parameter(weight, requires_grad=True)
        print('self.dist:', self.dist.shape)
    
    
    def interpolate_support_dims(self, hypercorr, spatial_size=None):
        bsz, ch, ha, wa, hb, wb = hypercorr.size()
        hypercorr = hypercorr.permute(0, 4, 5, 1, 2, 3).contiguous().view(bsz * hb * wb, ch, ha, wa)
        hypercorr = F.interpolate(hypercorr, spatial_size, mode='bilinear', align_corners=True)
        o_hb, o_wb = spatial_size
        hypercorr = hypercorr.view(bsz, hb, wb, ch, o_hb, o_wb).permute(0, 3, 4, 5, 1, 2).contiguous()
        return hypercorr

    def interpolate_query_dims(self, hypercorr, spatial_size=None):
        bsz, ch, ha, wa, hb, wb = hypercorr.size()
        hypercorr = hypercorr.permute(0, 2, 3, 1, 4, 5).contiguous().view(bsz * ha * wa, ch, hb, wb)
        hypercorr = F.interpolate(hypercorr, spatial_size, mode='bilinear', align_corners=True)
        o_ha, o_wa = spatial_size
        hypercorr = hypercorr.view(bsz, ha, wa, ch, o_ha, o_wa).permute(0, 3, 1, 2, 4, 5).contiguous()
        return hypercorr

    def forward(self, corr, if_dist=False):
        # Encode correlation from each layer (Squeezing building blocks)
        if if_dist:
            corr = corr * self.dist
        out_block1 = self.block1(corr)
        out_block2 = self.block2(out_block1)
        out_block3 = self.block3(out_block2)
        out_block4 = self.block4(out_block3)

        # Predict logits with the encoded 4D-tensor
        bsz, ch, _, _, _, _= out_block4.size()
        out_block4_pooled = out_block4.view(bsz, ch, -1).mean(-1)
        logits = self.mlp(out_block4_pooled).squeeze(-1).squeeze(-1)
        return logits