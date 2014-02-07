"""Collect importance sampler for Population Monte Carlo

"""

import numpy as _np
from math import exp as _exp
from copy import deepcopy as _cp
from ..tools._doc import _inherit_docstring
from ..tools import History as _History, merge_function_with_indicator as _indmerge

def calculate_expectation(samples, f):
    r'''Calculates the expectation value of function ``f`` using weighted
    samples (like the output of a PMC-run).

    Denoting :math:`x_n` as the sample n and :math:`w_n` as its (normalized)
    weight, the following is returned:

    .. math::

        \sum_{n=1}^{N} w_n f(x_n)
        \mathrm{\ \ where\ \ } \sum_{n=1}^{N}w_n \overset{!}{=} 1

    :param samples:

        Matrix-like numpy array; the samples to be used. The first column
        is used as (unnormalized) weights.

    :param f:

        Callable, the function to be evaluated.

    '''
    normalization = 0.
    out           = 0.
    for point in samples:
        normalization += point[0]
        out += point[0] * f(point[1:])
    return out/normalization

def calculate_mean(samples):
    r'''Calculates the mean of weighted samples (like the output of a
    PMC-run).

    :param samples:

        Matrix-like numpy array; the samples to be used. The first column
        is used as (unnormalized) weights.

    '''
    return _np.average(samples[:,1:], axis=0, weights=samples[:,0])

def calculate_covariance(samples):
    r'''Calculates the covariance matrix of weighted samples (like the
    output of a PMC-run).

    :param samples:

        Matrix-like numpy array; the samples to be used. The first column
        is used as (unnormalized) weights.

    '''
    sum_weights_sq = (samples[:,0].sum())**2
    sum_sq_weights = (samples[:,0]**2).sum()

    mean  = calculate_mean(samples)

    return sum_weights_sq / (sum_weights_sq - sum_sq_weights)  *\
           calculate_expectation(samples, lambda x: _np.einsum('i,j', x - mean, x - mean))

_docstring_params_importance_sampler = """:param target:

        The target density. Must be a function accepting a 1d numpy
        array and returning a float, namely :math:`\log(P(x))`,
        the log of the target `P`.

    :param proposal:

        The proposal density `q`.
        Should be of type :py:class:`pypmc.pmc.proposal.PmcProposal`.

    :param indicator:

        The indicator function receives a numpy array and returns bool.
        The target is only called if indicator(proposed_point) returns
        True. Otherwise, the proposed point will get zero-weight without
        call to target.
        Use this function to specify the support of the target.

        .. seealso::
            :py:mod:`pypmc.indicator_factory`

    :param prealloc:

        An integer, defines the number of Points for which memory in
        ``history`` is allocated. If more memory is needed, it will be
        allocated on demand.

        .. hint::
            Preallocating memory can speed up the calculation, in
            particular if it is known in advance how long the chains
            are run.

    :param rng:

        The rng passed to the proposal when calling proposal.propose

        .. important::
            ``rng`` must fulfill the requirements of your proposal
            :py:meth:`pypmc.pmc.proposal.PmcProposal.propose`

    """

class ImportanceSampler(object):
    __doc__ = r"""ImportanceSampler(target, proposal, indicator=None, prealloc=0,
    rng=numpy.random.mtrand)

    An importance sampler object; generates weighted samples from
    ``target`` using ``proposal``.

    """ + _docstring_params_importance_sampler
    def __init__(self, target, proposal, indicator=None, prealloc=0, rng=_np.random.mtrand):
        self.proposal = _cp(proposal)
        self.rng      = rng
        self.target   = _indmerge(target, indicator, -_np.inf)
        self.history  = _History(proposal.dim + 1, prealloc)

    def run(self, N=1, trace=False):
        '''Runs the sampler and stores the history of visited points into
        the member variable ``self.history``

        .. seealso::
            :py:class:`pypmc.tools.History`

        :param N:

            An int which defines the number of steps to run the chain.

        :param trace:

            Bool; if True, return an array containing the responsible
            component of ``self.proposal`` for each sample generated
            during this run.

            .. note::

                This option only works for proposals of type
                :py:class:`pypmc.pmc.proposal.MixtureProposal`

        '''
        if trace:
            this_run, origin = self._get_samples(N, trace=True)
            self._calculate_weights(this_run, N)
            return origin
        else:
            this_run = self._get_samples(N, trace=False)
            self._calculate_weights(this_run, N)

    def _calculate_weights(self, this_run, N):
        """Calculates and saves the weights of a run."""
        for i in range(N):
            tmp = this_run[i, 1:]
            tmp = self.target(tmp) - self.proposal.evaluate(tmp)
            this_run[i,0] = _exp(tmp)

    def _get_samples(self, N, trace):
        """Saves N samples from ``self.proposal`` to ``self.history``
        Does NOT calculate the weights.

        Returns a reference to the samples in ``self.history``.
        If trace is True, additionally returns an array indicating
        the responsible component. (MixtureProposal only)

        """
        # allocate an empty numpy array to store the run and append accept count
        # (importance sampling accepts all points)
        this_run = self.history.append(N)

        # store the proposed points (weights are still to be calculated)
        if trace:
            this_run[:,1:], origin = self.proposal.propose(N, self.rng, trace=True)
            return this_run, origin
        else:
            this_run[:,1:] = self.proposal.propose(N, self.rng)
            return this_run

class DeterministicIS(ImportanceSampler):
    __doc__ = r"""DeterministicIS(target, proposal, indicator = None, prealloc = 0,
    rng = numpy.random.mtrand)

    An importance sampler object; generates weighted samples from
    ``target`` using ``proposal``. Calculates `deterministic mixture
    weights` according to [Cor+12]_

    """ + _docstring_params_importance_sampler
    def __init__(self, *args, **kwargs):
        super(DeterministicIS, self).__init__(*args, **kwargs)

        # save all past proposals in this list
        self.proposal_history = []

        # save all evaluated target and proposal values in this History object
        self._deltas_targets_evaluated = _History(2, self.history.prealloc)

    def clear(self):
        """Deletes the history"""
        self.history.clear()
        self._deltas_targets_evaluated.clear()
        self.proposal_history = []

    @_inherit_docstring(ImportanceSampler)
    def _calculate_weights(self, this_weights_samples, this_N):
        inconsistency_message = 'Inconsistent state encountered. If you used ' + \
                                '``self.history.clear()`` try ``self.clear()`` instead.'

        # append proposal for this run to history
        self.proposal_history.append(_cp(self.proposal))

        # allocate memory for new target and proposal evaluations
        this_deltas_targets = self._deltas_targets_evaluated.append(this_N)

        # create references
        this_weights = this_weights_samples[:,0 ]
        this_samples = this_weights_samples[:,1:]
        this_deltas  = this_deltas_targets [:,0 ]
        this_targets = this_deltas_targets [:,1 ]
        old_weights_samples = self.history[:-1]
        old_deltas_targets  = self._deltas_targets_evaluated[:-1]
        assert len(old_weights_samples) == len(old_deltas_targets), inconsistency_message

        all_weights_samples = self.history[:]
        all_deltas_targets  = self._deltas_targets_evaluated[:]
        assert len(all_weights_samples) == len(all_deltas_targets), inconsistency_message

        all_weights = all_weights_samples[:,0 ]
        all_samples = all_weights_samples[:,1:]
        all_deltas  = all_deltas_targets [:,0 ]
        all_targets = all_deltas_targets [:,1 ]


        # evaluate the target at the new samples
        for i, sample in enumerate(this_samples):
            # exp because the self.target returns the log of the target
            this_targets[i] = _exp(self.target(sample))

        # calculate the deltas for the new samples
        this_deltas[:] = 0.
        for i_sample, sample in enumerate(this_samples):
            for i_run, i_samples in enumerate(self.history):
                this_deltas[i_sample] += len(i_samples) * _exp( self.proposal_history[i_run].evaluate(sample) )

        assert i_run + 1 == len(self.proposal_history), inconsistency_message


        # not to be done if this is the first run
        if old_weights_samples.size:
            old_weights = old_weights_samples[:,0 ]
            old_samples = old_weights_samples[:,1:]
            old_deltas  = old_deltas_targets [:,0 ]
            old_targets = old_deltas_targets [:,1 ]

            # calculate the deltas for the old samples
            for i_sample, sample in enumerate(old_samples):
                old_deltas[i_sample] += this_N * _exp( self.proposal_history[-1].evaluate(sample) )


        # calculate the weights (Algorithm1 in [Cor+12])
        all_weights[:] = all_targets / (all_deltas / len(all_weights_samples))
