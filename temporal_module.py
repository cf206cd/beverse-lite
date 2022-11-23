import torch
import torch.nn as nn

class CausalConv3d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=(2, 3, 3), dilation=(1, 1, 1), bias=False):
        super().__init__()
        assert len(kernel_size) == 3, 'kernel_size must be a 3-tuple.'
        time_pad = (kernel_size[0] - 1) * dilation[0]
        height_pad = ((kernel_size[1] - 1) * dilation[1]) // 2
        width_pad = ((kernel_size[2] - 1) * dilation[2]) // 2

        # Pad temporally on the left
        self.pad = nn.ConstantPad3d(padding=(width_pad, width_pad, height_pad, height_pad, time_pad, 0), value=0)
        self.conv = nn.Conv3d(in_channels, out_channels, kernel_size, dilation=dilation, stride=1, padding=0, bias=bias)
        self.norm = nn.BatchNorm3d(out_channels)
        self.activation = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.pad(x)
        x = self.conv(x)
        x = self.norm(x)
        x = self.activation(x)
        return x

def conv_1x1x1_norm_activated(in_channels, out_channels):
    """1x1x1 3D convolution, normalization and activation layer."""
    return nn.Sequential(
            nn.Conv3d(in_channels, out_channels, kernel_size=1, bias=False),
            nn.BatchNorm3d(out_channels),
            nn.ReLU(inplace=True),
        )

class Bottleneck3D(nn.Module):
    """
    Defines a bottleneck module with a residual connection
    """

    def __init__(self, in_channels, out_channels=None, kernel_size=(2, 3, 3), dilation=(1, 1, 1)):
        super().__init__()
        bottleneck_channels = in_channels // 2
        out_channels = out_channels or in_channels

        self.layers = nn.Sequential(
                    # First projection with 1x1 kernel
                    conv_1x1x1_norm_activated(in_channels, bottleneck_channels),
                    # Second conv block
                    CausalConv3d(
                            bottleneck_channels,
                            bottleneck_channels,
                            kernel_size=kernel_size,
                            dilation=dilation,
                            bias=False,
                    ),
                    # Final projection with 1x1 kernel
                    conv_1x1x1_norm_activated(bottleneck_channels, out_channels),
        )

        if out_channels != in_channels:
            self.projection = nn.Sequential(
                nn.Conv3d(in_channels, out_channels, kernel_size=1, bias=False),
                nn.BatchNorm3d(out_channels),
            )
        else:
            self.projection = nn.Identity()

    def forward(self, x):
        x_residual = self.layers(x)
        x_features = self.projection(x)
        return x_residual + x_features

class PyramidSpatioTemporalPooling(nn.Module):
    """ Spatio-temporal pyramid pooling.
        Performs 3D average pooling followed by 1x1x1 convolution to reduce the number of channels and upsampling.
        Setting contains a list of kernel_size: usually it is [(2, h, w), (2, h//2, w//2), (2, h//4, w//4)]
    """

    def __init__(self, in_channels, reduction_channels, pool_sizes):
        super().__init__()
        self.features = []
        for pool_size in pool_sizes:
            assert pool_size[0] == 2, (
                "Time kernel should be 2 as PyTorch raises an error when" "padding with more than half the kernel size"
            )
            stride = (1, *pool_size[1:])
            padding = (pool_size[0] - 1, 0, 0)
            self.features.append(
                nn.Sequential(
                        # Pad the input tensor but do not take into account zero padding into the average.
                        torch.nn.AvgPool3d(
                            kernel_size=pool_size, stride=stride, padding=padding, count_include_pad=False
                        ),
                        conv_1x1x1_norm_activated(in_channels, reduction_channels),
                    )
                )
        self.features = nn.ModuleList(self.features)

    def forward(self, x):
        b, _, t, h, w = x.shape
        # Do not include current tensor when concatenating
        out = []
        for f in self.features:
            # Remove unnecessary padded values (time dimension) on the right
            x_pool = f(x)[:, :, :-1].contiguous()
            c = x_pool.shape[1]
            x_pool = nn.functional.interpolate(
                x_pool.view(b * t, c, *x_pool.shape[-2:]), (h, w), mode='bilinear', align_corners=False
            )
            x_pool = x_pool.view(b, c, t, h, w)
            out.append(x_pool)
        out = torch.cat(out, 1)
        return out

class TemporalModule(nn.Module):
    """ Temporal block with the following layers:
        - 2x3x3, 1x3x3, spatio-temporal pyramid pooling
        - dropout
        - skip connection.
    """

    def __init__(self, in_channels, out_channels=None, use_pyramid_pooling=False, pool_sizes=None):
        super().__init__()
        self.in_channels = in_channels
        self.half_channels = in_channels // 2
        self.out_channels = out_channels or self.in_channels
        self.kernels = [(2, 3, 3), (1, 3, 3)]

        # Flag for spatio-temporal pyramid pooling
        self.use_pyramid_pooling = use_pyramid_pooling

        # 3 convolution paths: 2x3x3, 1x3x3, 1x1x1
        self.convolution_paths = []
        for kernel_size in self.kernels:
            self.convolution_paths.append(
                nn.Sequential(
                    conv_1x1x1_norm_activated(self.in_channels, self.half_channels),
                    CausalConv3d(self.half_channels, self.half_channels, kernel_size=kernel_size),
                )
            )
        self.convolution_paths.append(conv_1x1x1_norm_activated(self.in_channels, self.half_channels))
        self.convolution_paths = nn.ModuleList(self.convolution_paths)

        agg_in_channels = len(self.convolution_paths) * self.half_channels

        if self.use_pyramid_pooling:
            assert pool_sizes is not None, "setting must contain the list of kernel_size, but is None."
            reduction_channels = self.in_channels // 3
            self.pyramid_pooling = PyramidSpatioTemporalPooling(self.in_channels, reduction_channels, pool_sizes)
            agg_in_channels += len(pool_sizes) * reduction_channels

        # Feature aggregation
        self.aggregation = conv_1x1x1_norm_activated(agg_in_channels, self.out_channels)

        if self.out_channels != self.in_channels:
            self.projection = nn.Sequential(
                nn.Conv3d(self.in_channels, self.out_channels, kernel_size=1, bias=False),
                nn.BatchNorm3d(self.out_channels),
            )
        else:
            self.projection = nn.Identity()

    def forward(self, x):
        x_paths = []
        for conv in self.convolution_paths:
            x_paths.append(conv(x))
        x_residual = torch.cat(x_paths, dim=1)
        if self.use_pyramid_pooling:
            x_pool = self.pyramid_pooling(x)
            x_residual = torch.cat([x_residual, x_pool], dim=1)
        x_residual = self.aggregation(x_residual)

        x = self.projection(x)
        x = x + x_residual
        return x

class TemporalBlock(nn.Module):
    def __init__(self,in_channels,receptive_field,input_shape,start_out_channels=64,extra_in_channels=0,
            n_spatial_layers_between_temporal_layers=0,use_pyramid_pooling=True):
        super().__init__()
        self.receptive_field = receptive_field
        n_temporal_layers = receptive_field - 1

        h, w = input_shape
        modules = []

        block_in_channels = in_channels
        block_out_channels = start_out_channels

        for _ in range(n_temporal_layers):
            if use_pyramid_pooling:
                use_pyramid_pooling = True
                pool_sizes = [(2, h, w)]
            else:
                use_pyramid_pooling = False
                pool_sizes = None
            temporal = TemporalBlock(
                block_in_channels,
                block_out_channels,
                use_pyramid_pooling=use_pyramid_pooling,
                pool_sizes=pool_sizes,
            )
            spatial = [
                Bottleneck3D(block_out_channels, block_out_channels, kernel_size=(1, 3, 3))
                for _ in range(n_spatial_layers_between_temporal_layers)
            ]
            temporal_spatial_layers = nn.Sequential(temporal, *spatial)
            modules.extend(temporal_spatial_layers)

            block_in_channels = block_out_channels
            block_out_channels += extra_in_channels

        self.out_channels = block_in_channels

        self.model = nn.Sequential(*modules)

    def forward(self, x):
        # Reshape input tensor to (batch, C, time, H, W)
        x = x.permute(0, 2, 1, 3, 4)
        x = self.model(x)
        x = x.permute(0, 2, 1, 3, 4).contiguous()
        return x[:, (self.receptive_field - 1):]

if __name__ == "__main__":
    x = torch.zeros(4,7,64,200,200)
    net = TemporalModule(64,4,(200,200))
    res = net(x)
    print(res.shape)