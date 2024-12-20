from .neurons import LIF
import torch
from torch import nn


class Funky(LIF):
    """
    First-order "funky" leaky integrate-and-fire neuron model.
    Spike threshold is randomly moved up or down when a spike is fired,
    by an amount drawn from a normal distribution with mean 0
    and standard deviation "funkiness".
    Input is assumed to be a current injection.
    Membrane potential decays exponentially with rate beta.
    For :math:`U[T] > U_{\\rm thr} ⇒ S[T+1] = 1`.

    If `reset_mechanism = "subtract"`, then :math:`U[t+1]` will have
    `threshold` subtracted from it whenever the neuron emits a spike:

    .. math::

            U[t+1] = βU[t] + I_{\\rm in}[t+1] - RU_{\\rm thr}

    If `reset_mechanism = "zero"`, then :math:`U[t+1]` will be set to `0`
    whenever the neuron emits a spike:

    .. math::

            U[t+1] = βU[t] + I_{\\rm syn}[t+1] - R(βU[t] + I_{\\rm in}[t+1])

    * :math:`I_{\\rm in}` - Input current
    * :math:`U` - Membrane potential
    * :math:`U_{\\rm thr}` - Membrane threshold
    * :math:`R` - Reset mechanism: if active, :math:`R = 1`, otherwise \
        :math:`R = 0`
    * :math:`β` - Membrane potential decay rate

    Example::

        import torch
        import torch.nn as nn
        import snntorch as snn

        beta = 0.5

        # Define Network
        class Net(nn.Module):
            def __init__(self):
                super().__init__()

                # initialize layers
                self.fc1 = nn.Linear(num_inputs, num_hidden)
                self.lif1 = snn.Leaky(beta=beta)
                self.fc2 = nn.Linear(num_hidden, num_outputs)
                self.lif2 = snn.Leaky(beta=beta)

            def forward(self, x, mem1, spk1, mem2):
                cur1 = self.fc1(x)
                spk1, mem1 = self.lif1(cur1, mem1)
                cur2 = self.fc2(spk1)
                spk2, mem2 = self.lif2(cur2, mem2)
                return mem1, spk1, mem2, spk2


    :param beta: membrane potential decay rate. Clipped between 0 and 1
        during the forward-pass. May be a single-valued tensor (i.e., equal
        decay rate for all neurons in a layer), or multi-valued (one weight per
        neuron).
    :type beta: float or torch.tensor

    :param funkiness: Controls how much the spike threshold should be modified
    each time a spike is fired. Formally, funkiness is the standard deviation 
    of the normal distribution from which a the random threshold modification
    is drawn. Defaults to 0 (making the Funky neuron equivalent to a standard
    Leaky neuron).
    :type funkiness: float, optional

    :param threshold: Threshold for :math:`mem` to reach in order to
        generate a spike `S=1`. Defaults to 1
    :type threshold: float, optional

    :param spike_grad: Surrogate gradient for the term dS/dU. Defaults to
        None (corresponds to ATan surrogate gradient. See
        `snntorch.surrogate` for more options)
    :type spike_grad: surrogate gradient function from snntorch.surrogate,
        optional

    :param surrogate_disable: Disables surrogate gradients regardless of
        `spike_grad` argument. Useful for ONNX compatibility. Defaults
        to False
    :type surrogate_disable: bool, Optional

    :param init_hidden: Instantiates state variables as instance variables.
        Defaults to False
    :type init_hidden: bool, optional

    :param inhibition: If `True`, suppresses all spiking other than the
        neuron with the highest state. Defaults to False
    :type inhibition: bool, optional

    :param learn_beta: Option to enable learnable beta. Defaults to False
    :type learn_beta: bool, optional

    :param reset_mechanism: Defines the reset mechanism applied to \
    :math:`mem` each time the threshold is met. Reset-by-subtraction: \
        "subtract", reset-to-zero: "zero", none: "none". Defaults to "subtract"
    :type reset_mechanism: str, optional

    :param state_quant: If specified, hidden state :math:`mem` is quantized
        to a valid state for the forward pass. Defaults to False
    :type state_quant: quantization function from snntorch.quant, optional

    :param output: If `True` as well as `init_hidden=True`, states are
        returned when neuron is called. Defaults to False
    :type output: bool, optional

    :param graded_spikes_factor: output spikes are scaled this value, if specified. Defaults to 1.0
    :type graded_spikes_factor: float or torch.tensor

    :param learn_graded_spikes_factor: Option to enable learnable graded spikes. Defaults to False
    :type learn_graded_spikes_factor: bool, optional

    :param reset_delay: If `True`, a spike is returned with a one-step delay after the threshold is reached.
        Defaults to True
    :type reset_delay: bool, optional

    Inputs: \\input_, mem_0
        - **input_** of shape `(batch, input_size)`: tensor containing input
            features
        - **mem_0** of shape `(batch, input_size)`: tensor containing the
            initial membrane potential for each element in the batch.

    Outputs: spk, mem_1
        - **spk** of shape `(batch, input_size)`: tensor containing the
            output spikes.
        - **mem_1** of shape `(batch, input_size)`: tensor containing the
            next membrane potential for each element in the batch

    Learnable Parameters:
        - **Leaky.beta** (torch.Tensor) - optional learnable weights must be
            manually passed in, of shape `1` or (input_size).
        - **Leaky.threshold** (torch.Tensor) - optional learnable thresholds
            must be manually passed in, of shape `1` or`` (input_size).

    """

    def __init__(
        self,
        beta,
        funkiness=0.0,
        threshold=1.0,
        spike_grad=None,
        surrogate_disable=False,
        init_hidden=False,
        inhibition=False,
        learn_beta=False,
        learn_threshold=False,
        reset_mechanism="subtract",
        state_quant=False,
        output=False,
        graded_spikes_factor=1.0,
        learn_graded_spikes_factor=False,
        reset_delay=True,
    ):
        super().__init__(
            beta,
            threshold,
            spike_grad,
            surrogate_disable,
            init_hidden,
            inhibition,
            learn_beta,
            learn_threshold,
            reset_mechanism,
            state_quant,
            output,
            graded_spikes_factor,
            learn_graded_spikes_factor,
        )

        self._init_mem()

        if self.reset_mechanism_val == 0:  # reset by subtraction
            self.state_function = self._base_sub
        elif self.reset_mechanism_val == 1:  # reset to zero
            self.state_function = self._base_zero
        elif self.reset_mechanism_val == 2:  # no reset, pure integration
            self.state_function = self._base_int

        self.reset_delay = reset_delay
        self.funkiness = funkiness

    def _init_mem(self):
        mem = torch.zeros(0)
        self.register_buffer("mem", mem, False)

    def reset_mem(self):
        self.mem = torch.zeros_like(self.mem, device=self.mem.device)
        return self.mem

    def init_funky(self):
        """Deprecated, use :class:`Funky.reset_mem` instead"""
        return self.reset_mem()

    def forward(self, input_, mem=None):

        if not mem == None:
            self.mem = mem

        if self.init_hidden and not mem == None:
            raise TypeError(
                "`mem` should not be passed as an argument while `init_hidden=True`"
            )

        if not self.mem.shape == input_.shape:
            self.mem = torch.zeros_like(input_, device=self.mem.device)

        self.reset = self.mem_reset(self.mem)
        self.mem = self.state_function(input_)

        if self.state_quant:
            self.mem = self.state_quant(self.mem)

        if self.inhibition:
            spk = self.fire_inhibition(
                self.mem.size(0), self.mem
            )  # batch_size
        else:
            threshold_before_spike = self.threshold
            spk = self.fire(self.mem)

        if not self.reset_delay:
            do_reset = (
                spk / self.graded_spikes_factor - self.reset
            )  # avoid double reset
            if self.reset_mechanism_val == 0:  # reset by subtraction
                self.mem = self.mem - do_reset * threshold_before_spike
            elif self.reset_mechanism_val == 1:  # reset to zero
                self.mem = self.mem - do_reset * self.mem

        if self.output:
            return spk, self.mem
        elif self.init_hidden:
            return spk
        else:
            return spk, self.mem


    # Override the parent fire method to fire in a funky silly way
    def fire(self, mem):
        """Generates spike if mem > threshold and updates threshold randomly after firing.
        Returns spk."""

        if self.state_quant:
            mem = self.state_quant(mem)

        mem_shift = mem - self.threshold
        spk = self.spike_grad(mem_shift)

        spk = spk * self.graded_spikes_factor

        # Update threshold randomly if spike !!
        if torch.any(spk):
            self.threshold += torch.normal(mean=0.0, std=self.funkiness, size=self.threshold.shape)

        return spk


    def _base_state_function(self, input_):
        base_fn = self.beta.clamp(0, 1) * self.mem + input_
        return base_fn

    def _base_sub(self, input_):
        return self._base_state_function(input_) - self.reset * self.threshold

    def _base_zero(self, input_):
        self.mem = (1 - self.reset) * self.mem
        return self._base_state_function(input_)

    def _base_int(self, input_):
        return self._base_state_function(input_)

    @classmethod
    def detach_hidden(cls):
        """Returns the hidden states, detached from the current graph.
        Intended for use in truncated backpropagation through time where
        hidden state variables are instance variables."""

        for layer in range(len(cls.instances)):
            if isinstance(cls.instances[layer], Funky):
                cls.instances[layer].mem.detach_()

    @classmethod
    def reset_hidden(cls):
        """Used to clear hidden state variables to zero.
        Intended for use where hidden state variables are instance variables.
        Assumes hidden states have a batch dimension already."""
        for layer in range(len(cls.instances)):
            if isinstance(cls.instances[layer], Funky):
                cls.instances[layer].mem = torch.zeros_like(
                    cls.instances[layer].mem,
                    device=cls.instances[layer].mem.device,
                )
