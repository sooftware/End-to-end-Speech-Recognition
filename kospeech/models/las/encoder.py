# Copyright (c) 2020, Soohwan Kim. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import torch.nn as nn
from torch import Tensor
from typing import Tuple, Optional

from kospeech.models.base import BaseEncoder
from kospeech.models.modules import Linear, Transpose
from kospeech.models.conv import (
    VGGExtractor,
    DeepSpeech2Extractor,
)


class EncoderRNN(BaseEncoder):
    """
    Converts low level speech signals into higher level features

    Args:
        input_dim (int): dimension of input vector
        hidden_state_dim (int): the number of features in the hidden state `h`
        num_layers (int, optional): number of recurrent layers (default: 1)
        bidirectional (bool, optional): if True, becomes a bidirectional encoder (defulat: False)
        rnn_type (str, optional): type of RNN cell (default: lstm)
        dropout_p (float, optional): dropout probability (default: 0.3)
        extractor (str): type of CNN extractor (default: vgg)
        activation (str): type of activation function (default: hardtanh)

    Inputs: inputs, input_lengths
        - **inputs**: list of sequences, whose length is the batch size and within which each sequence is list of tokens
        - **input_lengths**: list of sequence lengths

    Returns: encoder_outputs, encoder_log__probs, output_lengths
        - **encoder_outputs**: tensor containing the encoded features of the input sequence
        - **encoder_log__probs**: tensor containing log probability for ctc loss
        - **output_lengths**: list of sequence lengths produced by Listener
    """
    supported_rnns = {
        'lstm': nn.LSTM,
        'gru': nn.GRU,
        'rnn': nn.RNN,
    }
    supported_extractors = {
        'ds2': DeepSpeech2Extractor,
        'vgg': VGGExtractor,
    }

    def __init__(
            self,
            input_dim: int,                          # size of input
            num_classes: int = None,                 # number of class
            hidden_state_dim: int = 512,             # dimension of RNN`s hidden state
            dropout_p: float = 0.3,                  # dropout probability
            num_layers: int = 3,                     # number of RNN layers
            bidirectional: bool = True,              # if True, becomes a bidirectional encoder
            rnn_type: str = 'lstm',                  # type of RNN cell
            extractor: str = 'vgg',                  # type of CNN extractor
            activation: str = 'hardtanh',            # type of activation function
            joint_ctc_attention: bool = False,       # Use CTC Loss & Cross Entropy Joint Learning
    ) -> None:
        super(EncoderRNN, self).__init__()
        self.hidden_state_dim = hidden_state_dim
        self.joint_ctc_attention = joint_ctc_attention
        extractor = self.supported_extractors[extractor.lower()]
        rnn_cell = self.supported_rnns[rnn_type.lower()]
        self.conv = extractor(input_dim, activation=activation)
        self.rnn = rnn_cell(
            input_size=self.conv.get_output_dim(),
            hidden_size=hidden_state_dim,
            num_layers=num_layers,
            bias=True,
            batch_first=True,
            dropout=dropout_p,
            bidirectional=bidirectional,
        )

        if self.joint_ctc_attention:
            self.fc = nn.Sequential(
                nn.BatchNorm1d(self.hidden_state_dim << 1),
                Transpose(shape=(1, 2)),
                nn.Dropout(dropout_p),
                Linear(self.hidden_state_dim << 1, num_classes, bias=False),
            )

    def forward(self, inputs: Tensor, input_lengths: Tensor) -> Tuple[Tensor, Tensor, Optional[Tensor]]:
        """
        inputs (torch.FloatTensor): (batch_size, sequence_length, dimension)
        input_lengths (torch.LongTensor): (batch_size)
        """
        encoder_log_probs = None
        features, output_lengths = self.conv(inputs, input_lengths)

        features = nn.utils.rnn.pack_padded_sequence(features.transpose(0, 1), output_lengths.cpu())
        encoder_outputs, hidden_states = self.rnn(features)
        encoder_outputs, _ = nn.utils.rnn.pad_packed_sequence(encoder_outputs)
        encoder_outputs = encoder_outputs.transpose(0, 1)

        if self.joint_ctc_attention:
            encoder_log_probs = self.fc(encoder_outputs.transpose(1, 2)).log_softmax(dim=2)

        return encoder_outputs, output_lengths, encoder_log_probs
