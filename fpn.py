import torch
import torch.nn as nn
import torch.nn.functional as F

class FPN(nn.Module):
    def __init__(self, in_channels, out_channels=512, out_ids=[0,]):
        super().__init__()
        self.in_channels = in_channels
        self.lateral_convs = nn.ModuleList()
        self.fpn_convs = nn.ModuleList()
        self.out_ids = out_ids
        for i,in_channel in enumerate(in_channels):
            lateral_conv = nn.Conv2d(in_channel,out_channels,1)
            self.lateral_convs.append(lateral_conv)
            if i in out_ids:
                fpn_conv = nn.Conv2d(out_channels,out_channels,3,padding=1)
                self.fpn_convs.append(fpn_conv)

    def forward(self, inputs):
        assert len(inputs) == len(self.in_channels)
        laterals = [
            lateral_conv(inputs[i])
            for i, lateral_conv in enumerate(self.lateral_convs)
        ]
        for i in range(len(laterals)-1,0,-1):
            prev_shape = laterals[i - 1].shape[2:]
            laterals[i - 1] += F.interpolate(laterals[i], size=prev_shape)
        outs = [self.fpn_convs[i](laterals[i]) for i in self.out_ids]
        return outs
