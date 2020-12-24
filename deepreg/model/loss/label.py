"""
Module provides different loss functions for calculating the dissimilarities between labels.
"""

import tensorflow as tf

from deepreg.model.loss.util import NegativeLossMixin
from deepreg.registry import REGISTRY

EPS = tf.keras.backend.epsilon()


def gauss_kernel1d(sigma: int) -> tf.Tensor:
    """
    Calculates a gaussian kernel.

    :param sigma: number defining standard deviation for
                  gaussian kernel.
    :return: shape = (dim, ) or ()
    """
    if sigma == 0:
        return tf.constant(0, tf.float32)
    else:
        tail = int(sigma * 3)
        k = tf.exp([-0.5 * x ** 2 / sigma ** 2 for x in range(-tail, tail + 1)])
        return k / tf.reduce_sum(k)


def cauchy_kernel1d(sigma: int) -> tf.Tensor:
    """
    Approximating cauchy kernel in 1d.

    :param sigma: int, defining standard deviation of kernel.
    :return: shape = (dim, ) or ()
    """
    if sigma == 0:
        return tf.constant(0, tf.float32)
    else:
        tail = int(sigma * 5)
        k = tf.math.reciprocal([((x / sigma) ** 2 + 1) for x in range(-tail, tail + 1)])
        return k / tf.reduce_sum(k)


class MultiScaleLoss(tf.keras.losses.Loss):
    """
    Apply the loss at different scales (gaussian or cauchy smoothing).
    It is assumed that loss values are between 0 and 1.
    """

    kernel_fn_dict = dict(gaussian=gauss_kernel1d, cauchy=cauchy_kernel1d)

    def __init__(
        self,
        scales=None,
        kernel: str = "gaussian",
        reduction=tf.keras.losses.Reduction.AUTO,
        name="MultiScaleLoss",
    ):
        """

        :param scales: if None, do not apply any
        :param kernel: gaussian or cauchy
        :param reduction:
        :param name:
        """
        super(MultiScaleLoss, self).__init__(reduction=reduction, name=name)
        assert kernel in ["gaussian", "cauchy"]
        self.scales = scales
        self.kernel = kernel

    def call(self, y_true, y_pred):
        if self.scales is None:
            return self._call(y_true=y_true, y_pred=y_pred)
        kernel_fn = self.kernel_fn_dict[self.kernel]
        loss = tf.stack(
            [
                self._call(
                    y_true=separable_filter3d(y_true, kernel_fn(s)),
                    y_pred=separable_filter3d(y_pred, kernel_fn(s)),
                )
                for s in self.scales
            ],
            axis=-1,
        )
        return tf.reduce_mean(loss, axis=-1)

    def _call(self, y_true, y_pred):
        """correspond to the loss without scaling"""
        raise NotImplementedError

    def get_config(self):
        config = super(MultiScaleLoss, self).get_config()
        config["scales"] = self.scales
        config["kernel"] = self.kernel
        return config


class DiceScore(MultiScaleLoss):
    """
    Calculates dice score:
    0. pos_w + neg_w = 1
    1. let y_prod = y_true * y_pred and y_sum  = y_true + y_pred
    2. num = 2 *  (pos_w * y_true * y_pred + neg_w * (1−y_true) * (1−y_pred))
           = 2 *  ((pos_w+neg_w) * y_prod - neg_w * y_sum + neg_w)
           = 2 *  (y_prod - neg_w * y_sum + neg_w)
    3. denom = (pos_w * (y_true + y_pred) + neg_w * (1−y_true + 1−y_pred))
             = (pos_w-neg_w) * y_sum + 2 * neg_w
             = (1-2*neg_w) * y_sum + 2 * neg_w
    4. dice score = num / denom

    where num and denom are summed over all axes except the batch axis.
    """

    def __init__(
        self,
        binary: bool = False,
        neg_weight: float = 0.0,
        scales=None,
        kernel: str = "gaussian",
        reduction=tf.keras.losses.Reduction.AUTO,
        name="DiceScore",
    ):
        """

        :param binary: if True, project y_true, y_pred to 0 or 1
        :param neg_weight: weight for negative class
        :param reduction:
        :param name:
        """
        super(DiceScore, self).__init__(
            scales=scales, kernel=kernel, reduction=reduction, name=name
        )
        assert 0 <= neg_weight <= 1
        self.binary = binary
        self.neg_weight = neg_weight

    def _call(self, y_true, y_pred):
        """
        :param y_true: shape = (batch, ...)
        :param y_pred: shape = (batch, ...)
        :return: shape = (batch,)
        """
        if self.binary:
            y_true = tf.cast(y_true >= 0.5, dtype=y_true.dtype)
            y_pred = tf.cast(y_pred >= 0.5, dtype=y_pred.dtype)

        # (batch, ...) -> (batch, d)
        y_true = tf.keras.layers.Flatten()(y_true)
        y_pred = tf.keras.layers.Flatten()(y_pred)

        y_prod = tf.reduce_sum(y_true * y_pred, axis=1)
        y_sum = tf.reduce_sum(y_true, axis=1) + tf.reduce_sum(y_pred, axis=1)

        numerator = 2 * (y_prod - self.neg_weight * y_sum + self.neg_weight)
        denominator = (1 - 2 * self.neg_weight) * y_sum + 2 * self.neg_weight

        return (numerator + EPS) / (denominator + EPS)

    def get_config(self):
        config = super(DiceScore, self).get_config()
        config["binary"] = self.binary
        config["neg_weight"] = self.neg_weight
        return config


@REGISTRY.register_loss(name="dice")
class DiceLoss(NegativeLossMixin, DiceScore):
    pass


@REGISTRY.register_loss(name="cross-entropy")
class CrossEntropy(MultiScaleLoss):
    """
    Calculates weighted binary cross- entropy:

        -loss = − pos_w * y_true log(y_pred) - (1−y_true) log(1−y_pred)
    """

    def __init__(
        self,
        binary: bool = False,
        neg_weight: float = 0.0,
        scales=None,
        kernel: str = "gaussian",
        reduction=tf.keras.losses.Reduction.AUTO,
        name="CrossEntropy",
    ):
        """

        :param binary: if True, project y_true, y_pred to 0 or 1
        :param neg_weight: weight for negative class
        :param reduction:
        :param name:
        """
        super(CrossEntropy, self).__init__(
            scales=scales, kernel=kernel, reduction=reduction, name=name
        )
        assert 0 <= neg_weight <= 1
        self.binary = binary
        self.neg_weight = neg_weight

    def _call(self, y_true, y_pred):
        """
        :param y_true: shape = (batch, ...)
        :param y_pred: shape = (batch, ...)
        :return: shape = (batch,)
        """
        if self.binary:
            y_true = tf.cast(y_true >= 0.5, dtype=y_true.dtype)
            y_pred = tf.cast(y_pred >= 0.5, dtype=y_pred.dtype)

        # (batch, ...) -> (batch, d)
        y_true = tf.keras.layers.Flatten()(y_true)
        y_pred = tf.keras.layers.Flatten()(y_pred)

        loss_pos = tf.reduce_mean(y_true * tf.math.log(y_pred + EPS), axis=1)
        loss_neg = tf.reduce_mean((1 - y_true) * tf.math.log(1 - y_pred + EPS), axis=1)
        return -(1 - self.neg_weight) * loss_pos - self.neg_weight * loss_neg

    def get_config(self):
        config = super(CrossEntropy, self).get_config()
        config["binary"] = self.binary
        config["neg_weight"] = self.neg_weight
        return config


class JaccardIndex(MultiScaleLoss):
    """
    Calculates Jaccard index:

    1. num = y_true * y_pred
    2. denom = y_true + y_pred - y_true * y_pred
    3. Jaccard index = num / denom
    """

    def __init__(
        self,
        binary: bool = False,
        scales=None,
        kernel: str = "gaussian",
        reduction=tf.keras.losses.Reduction.AUTO,
        name="JaccardIndex",
    ):
        """

        :param binary: if True, project y_true, y_pred to 0 or 1
        :param reduction:
        :param name:
        """
        super(JaccardIndex, self).__init__(
            scales=scales, kernel=kernel, reduction=reduction, name=name
        )
        self.binary = binary

    def _call(self, y_true, y_pred):
        """
        :param y_true: shape = (batch, ...)
        :param y_pred: shape = (batch, ...)
        :return: shape = (batch,)
        """
        if self.binary:
            y_true = tf.cast(y_true >= 0.5, dtype=y_true.dtype)
            y_pred = tf.cast(y_pred >= 0.5, dtype=y_pred.dtype)

        # (batch, ...) -> (batch, d)
        y_true = tf.keras.layers.Flatten()(y_true)
        y_pred = tf.keras.layers.Flatten()(y_pred)

        y_prod = tf.reduce_sum(y_true * y_pred, axis=1)
        y_sum = tf.reduce_sum(y_true, axis=1) + tf.reduce_sum(y_pred, axis=1)

        return (y_prod + EPS) / (y_sum - y_prod + EPS)

    def get_config(self):
        config = super(JaccardIndex, self).get_config()
        config["binary"] = self.binary
        return config


@REGISTRY.register_loss(name="jaccard")
class JaccardLoss(NegativeLossMixin, JaccardIndex):
    pass


def separable_filter3d(tensor: tf.Tensor, kernel: tf.Tensor) -> tf.Tensor:
    """
    Creates a 3d separable filter.

    Here `tf.nn.conv3d` accepts the `filters` argument of shape
    (filter_depth, filter_height, filter_width, in_channels, out_channels),
    where the first axis of `filters` is the depth not batch,
    and the input to `tf.nn.conv3d` is of shape
    (batch, in_depth, in_height, in_width, in_channels).

    :param tensor: shape = (batch, dim1, dim2, dim3)
    :param kernel: shape = (dim4,)
    :return: shape = (batch, dim1, dim2, dim3)
    """
    if len(kernel.shape) == 0:
        return tensor
    else:
        strides = [1, 1, 1, 1, 1]
        tensor = tf.nn.conv3d(
            tf.nn.conv3d(
                tf.nn.conv3d(
                    tf.expand_dims(tensor, axis=4),
                    filters=tf.reshape(kernel, [-1, 1, 1, 1, 1]),
                    strides=strides,
                    padding="SAME",
                ),
                filters=tf.reshape(kernel, [1, -1, 1, 1, 1]),
                strides=strides,
                padding="SAME",
            ),
            filters=tf.reshape(kernel, [1, 1, -1, 1, 1]),
            strides=strides,
            padding="SAME",
        )
        return tensor[:, :, :, :, 0]


def compute_centroid(mask: tf.Tensor, grid: tf.Tensor) -> tf.Tensor:
    """
    Calculate the centroid of the mask.

    :param mask: shape = (batch, dim1, dim2, dim3)
    :param grid: shape = (dim1, dim2, dim3, 3)
    :return: shape = (batch, 3), batch of vectors denoting
             location of centroids.
    """
    assert len(mask.shape) == 4
    assert len(grid.shape) == 4
    bool_mask = tf.expand_dims(
        tf.cast(mask >= 0.5, dtype=tf.float32), axis=4
    )  # (batch, dim1, dim2, dim3, 1)
    masked_grid = bool_mask * tf.expand_dims(
        grid, axis=0
    )  # (batch, dim1, dim2, dim3, 3)
    numerator = tf.reduce_sum(masked_grid, axis=[1, 2, 3])  # (batch, 3)
    denominator = tf.reduce_sum(bool_mask, axis=[1, 2, 3])  # (batch, 1)
    return (numerator + EPS) / (denominator + EPS)  # (batch, 3)


def compute_centroid_distance(
    y_true: tf.Tensor, y_pred: tf.Tensor, grid: tf.Tensor
) -> tf.Tensor:
    """
    Calculate the L2-distance between two tensors' centroids.

    :param y_true: tensor, shape = (batch, dim1, dim2, dim3)
    :param y_pred: tensor, shape = (batch, dim1, dim2, dim3)
    :param grid: tensor, shape = (dim1, dim2, dim3, 3)
    :return: shape = (batch,)
    """
    centroid_1 = compute_centroid(mask=y_pred, grid=grid)  # (batch, 3)
    centroid_2 = compute_centroid(mask=y_true, grid=grid)  # (batch, 3)
    return tf.sqrt(tf.reduce_sum((centroid_1 - centroid_2) ** 2, axis=1))


def foreground_proportion(y: tf.Tensor) -> tf.Tensor:
    """
    Calculating the percentage of foreground vs
    background per 3d volume.

    :param y: shape = (batch, dim1, dim2, dim3), a 3D label tensor
    :return: shape = (batch,)
    """
    y = tf.cast(y >= 0.5, dtype=tf.float32)
    return tf.reduce_sum(y, axis=[1, 2, 3]) / tf.reduce_sum(
        tf.ones_like(y), axis=[1, 2, 3]
    )
