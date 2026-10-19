import chess
import numpy as np
import pytest

from pairb.data import pack
from pairb.encode import encode_board
from pairb.linear import FEATURES, LinearCorrection, features, fit_candidates


def test_packed_features_match_live_encoding_and_empty_batches():
    b = chess.Board(); b.halfmove_clock = 37
    planes = encode_board(b)[None]
    assert np.allclose(features(pack(planes), [0.4], packed=True), features(planes, [0.4]))
    assert features(np.empty((0,19,8,8)), []).shape == (0, FEATURES)


def test_ridge_matches_independent_augmented_least_squares():
    rng = np.random.default_rng(3)
    # Only three varying planes entries: the reference solve stays small and full rank.
    p = np.zeros((60,19,8,8), dtype=np.uint8)
    bits = rng.integers(0,2,(60,3)); p[:,0,0,:3] = bits
    d1 = rng.uniform(-0.2,0.2,60)
    y = d1 + bits @ [0.1,-0.2,0.15] + 0.04 + 0.1*d1
    alpha = 0.01
    model, = fit_candidates(p,d1,y,[alpha])
    small = np.column_stack((bits,d1,np.ones(60)))
    penalty = np.zeros((4,5)); penalty[:,:4] = np.eye(4)*np.sqrt(60*alpha)
    reference = np.linalg.lstsq(np.vstack((small,penalty)), np.r_[y-d1,np.zeros(4)], rcond=None)[0]
    assert np.allclose(model.predict(p,d1,packed=True), d1 + small@reference, atol=1e-9)
    assert model.intercept == pytest.approx(reference[-1])
    chunked, = fit_candidates(p,d1,y,[alpha],batch=7)
    assert np.allclose(model.predict(p,d1,packed=True),chunked.predict(p,d1,packed=True),atol=1e-9)


def test_constant_inputs_have_unpenalized_intercept():
    p = np.zeros((4,19,8,8),dtype=np.uint8)
    model, = fit_candidates(p,np.zeros(4),np.array([0.2,0.3,0.4,0.5]),[100.0])
    assert model.intercept == pytest.approx(0.35)
    assert np.all(model.coef == 0)


def test_clipping_checkpoint_roundtrip_and_no_overwrite(tmp_path):
    model = LinearCorrection(np.zeros(FEATURES),0.4,0.1,{"splits":{"train":["g1"]}})
    p = np.zeros((2,19,8,8))
    assert model.predict(p,[0.9,-0.9]).tolist() == pytest.approx([1,-0.5])
    path = tmp_path/"best.npz"; model.save(path)
    loaded = LinearCorrection.load(path)
    assert loaded.metadata == model.metadata
    assert np.array_equal(model.predict(p,[0.9,-0.9]),loaded.predict(p,[0.9,-0.9]))
    with pytest.raises(FileExistsError): model.save(path)


@pytest.mark.parametrize("alpha",[0,-1,float('nan'),float('inf')])
def test_reject_invalid_regularization(alpha):
    with pytest.raises(ValueError):
        fit_candidates(np.zeros((2,19,8,8)),np.zeros(2),np.zeros(2),[alpha])


def test_reject_nonfinite_and_wrong_encoding(tmp_path):
    with pytest.raises(ValueError): features(np.zeros((1,19,8,8)),[float('nan')])
    path=tmp_path/"bad.npz"
    np.savez(path,format="unknown",encoding="unknown")
    with pytest.raises(ValueError,match="incompatible"): LinearCorrection.load(path)


def test_colour_swapped_boards_have_same_features():
    b=chess.Board(); b.push_uci('e2e4')
    assert np.array_equal(encode_board(b),encode_board(b.mirror()))
