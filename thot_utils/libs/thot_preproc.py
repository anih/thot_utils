# Author: Daniel Ortiz Mart\'inez
# -*- coding:utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import math
import re
import sys
from heapq import heappop, heappush

_global_n = 2
_global_lm_interp_prob = 0.5
_global_common_word_str = "<common_word>"
_global_number_str = "<number>"
_global_digit_str = "<digit>"
_global_alfanum_str = "<alfanum>"
_global_unk_word_str = "<unk>"
_global_eos_str = "<eos>"
_global_bos_str = "<bos>"
_global_categ_set = frozenset([_global_common_word_str, _global_number_str, _global_digit_str, _global_alfanum_str])
_global_digits = re.compile('\d')
_global_alnum = re.compile('[a-zA-Z0-9]+')
_global_a_par = 7
_global_maxniters = 100000
_global_tm_smooth_prob = 0.000001

# xml annotation variables
grp_ann = "phr_pair_annot"
src_ann = "src_segm"
trg_ann = "trg_segm"
dic_patt = u"(<%s>)[ ]*(<%s>)(.+?)(<\/%s>)[ ]*(<%s>)(.+?)(<\/%s>)[ ]*(<\/%s>)" % (grp_ann,
                                                                                  src_ann, src_ann,
                                                                                  trg_ann, trg_ann,
                                                                                  grp_ann)
len_ann = "length_limit"
len_patt = u"(<%s>)[ ]*(\d+)[ ]*(</%s>)" % (len_ann, len_ann)

_annotation = re.compile(dic_patt + "|" + len_patt)


class TransModel(object):
    def __init__(self, model_provider):
        self.model_provider = model_provider

    def obtain_opts_for_src(self, src_words):
        return self.model_provider.get_targets(src_words)

    def obtain_srctrg_count(self, src_words, trg_words):
        return self.model_provider.get_target_count(src_words, trg_words)

    def obtain_trgsrc_prob(self, src_words, trg_words):
        sc = self.obtain_src_count(src_words)
        if sc == 0:
            return 0
        else:
            stc = self.obtain_srctrg_count(src_words, trg_words)
            return float(stc) / float(sc)

    def obtain_trgsrc_prob_smoothed(self, src_words, trg_words):
        sc = self.obtain_src_count(src_words)
        if sc == 0:
            return _global_tm_smooth_prob
        else:
            stc = self.obtain_srctrg_count(src_words, trg_words)
            return (1 - _global_tm_smooth_prob) * (float(stc) / float(sc))

    def obtain_src_count(self, src_words):
        return self.model_provider.get_source_count(src_words)

    def get_mon_hyp_state(self, hyp):
        if len(hyp.data.coverage) == 0:
            return 0
        else:
            return hyp.data.coverage[len(hyp.data.coverage) - 1]


class LangModel:
    def __init__(self, provider, ngrams_length, interp_prob=None):
        self.provider = provider
        self.ngrams_length = ngrams_length
        self.set_interp_prob(interp_prob or _global_lm_interp_prob)

    def set_interp_prob(self, interp_prob):
        if interp_prob > 0.99:
            self.interp_prob = 0.99
        elif interp_prob < 0:
            self.interp_prob = 0
        else:
            self.interp_prob = interp_prob

    def obtain_ng_count(self, ngram):
        return self.provider.get_count(ngram)

    def obtain_trgsrc_prob(self, ngram):
        if ngram == "":
            return 1.0 / self.obtain_ng_count("")
        else:
            hc = self.obtain_ng_count(self.remove_newest_word(ngram))
            if hc == 0:
                return 0
            else:
                ngc = self.obtain_ng_count(ngram)
                return ngc / hc

    def obtain_trgsrc_interp_prob(self, ngram):
        ng_array = ngram.split()
        if len(ng_array) == 0:
            return self.obtain_trgsrc_prob(ngram)
        else:
            return self.interp_prob * self.obtain_trgsrc_prob(ngram) + (
                                                                           1 - self.interp_prob) * \
                                                                       self.obtain_trgsrc_interp_prob(
                                                                           self.remove_oldest_word(ngram))

    def remove_newest_word(self, ngram):
        ng_array = ngram.split()
        if len(ng_array) <= 1:
            return ""
        else:
            result = ng_array[0]
            for i in range(1, len(ng_array) - 1):
                result = result + " " + ng_array[i]
            return result

    def remove_oldest_word(self, ngram):
        ng_array = ngram.split()
        if len(ng_array) <= 1:
            return ""
        else:
            result = ng_array[1]
            for i in range(2, len(ng_array)):
                result = result + " " + ng_array[i]
            return result

    def lm_preproc(self, trans_raw_word_array, lmvoc):
        # Do not alter words
        return trans_raw_word_array

    def get_lm_state(self, words):
        # Obtain array of previous words including BOS symbol
        words_array_aux = words.split()
        words_array = []
        words_array.append(_global_bos_str)
        for i in range(len(words_array_aux)):
            words_array.append(words_array_aux[i])

        # Obtain history from array
        len_hwa = len(words_array)
        hist = ""
        for i in range(self.ngrams_length - 1):
            if i < len(words_array):
                word = words_array[len_hwa - 1 - i]
                if hist == "":
                    hist = word
                else:
                    hist = word + " " + hist
        return hist

    def get_hyp_state(self, hyp):
        return self.get_lm_state(hyp.data.words)


class BfsHypdata:
    def __init__(self):
        self.coverage = []
        self.words = ""

    def __str__(self):
        result = "cov:"
        for k in range(len(self.coverage)):
            result = result + " " + str(self.coverage[k])
        result = result + " ; words: " + self.words.encode("utf-8")
        return result


class Hypothesis:
    def __init__(self):
        self.score = 0
        self.data = BfsHypdata()

    def __cmp__(self, other):
        return cmp(other.score, self.score)


class PriorityQueue:
    def __init__(self):
        self.heap = []

    def empty(self):
        return len(self.heap) == 0

    def put(self, item):
        heappush(self.heap, item)

    def get(self):
        return heappop(self.heap)


class StateInfoDict:
    def __init__(self):
        self.recomb_map = {}

    def empty(self):
        return len(self.recomb_map) == 0

    def insert(self, state_info, score):
        # Update recombination info
        if state_info in self.recomb_map:
            if score > self.recomb_map[state_info]:
                self.recomb_map[state_info] = score
        else:
            self.recomb_map[state_info] = score

    def get(self):
        return heappop(self.heap)

    def hyp_recombined(self, state_info, score):

        if state_info in self.recomb_map:
            if score < self.recomb_map[state_info]:
                return True
            else:
                return False
        else:
            return False


class StateInfo:
    def __init__(self, tm_state, lm_state):
        self.tm_state = tm_state
        self.lm_state = lm_state

    def __hash__(self):
        return hash((self.tm_state, self.lm_state))

    def __eq__(self, other):
        return (self.tm_state, self.lm_state) == (other.tm_state, other.lm_state)


def obtain_state_info(tmodel, lmodel, hyp):
    return StateInfo(tmodel.get_mon_hyp_state(hyp), lmodel.get_hyp_state(hyp))


def transform_word(word):
    if word.isdigit():
        if len(word) > 1:
            return _global_number_str
        else:
            return _global_digit_str
    elif is_number(word):
        return _global_number_str
    elif is_alnum(word) and bool(_global_digits.search(word)):
        return _global_alfanum_str
    elif len(word) > 5:
        return _global_common_word_str
    else:
        return word


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        pass
    return False


def is_alnum(s):
    res = _global_alnum.match(s)
    if res is None:
        return False
    return True


def categorize(sentence):
    skeleton = annotated_string_to_xml_skeleton(sentence)
    # Categorize words
    categ_word_array = []
    len_ann_active = False
    for is_tag, word in skeleton:
        if is_tag:
            # Treat xml tag
            categ_word_array.append(word)
            if word == '<' + len_ann + '>':
                len_ann_active = True
            elif word == '</' + len_ann + '>':
                len_ann_active = False
        else:
            # Categorize group of words
            word_array = word.split()
            for inner_word in word_array:
                if not len_ann_active:
                    categ_word_array.append(categorize_word(inner_word))
                else:
                    categ_word_array.append(word)

    return u' '.join(categ_word_array)


def categorize_word(word):
    if word.isdigit() == True:
        if len(word) > 1:
            return _global_number_str
        else:
            return _global_digit_str
    elif is_number(word) == True:
        return _global_number_str
    elif is_alnum(word) == True and bool(_global_digits.search(word)) == True:
        return _global_alfanum_str
    else:
        return word


def is_categ(word):
    if word in _global_categ_set:
        return True
    else:
        return False


def extract_alig_info(hyp_word_array):
    # Initialize output variables
    srcsegms = []
    trgcuts = []

    # Scan hypothesis information
    info_found = False
    for i in range(len(hyp_word_array)):
        if hyp_word_array[i] == "hypkey:" and hyp_word_array[i - 1] == "|":
            info_found = True
            i -= 2
            break;

    if info_found:
        # Obtain target segment cuts
        trgcuts_found = False
        while i > 0:
            if hyp_word_array[i] != "|":
                trgcuts.append(int(hyp_word_array[i]))
                i -= 1
            else:
                trgcuts_found = True
                i -= 1
                break
        trgcuts.reverse()

        if trgcuts_found:
            # Obtain source segments
            srcsegms_found = False
            while i > 0:
                if hyp_word_array[i] != "|":
                    if i > 3:
                        srcsegms.append((int(hyp_word_array[i - 3]), int(hyp_word_array[i - 1])))
                    i -= 5
                else:
                    srcsegms_found = True
                    break
            srcsegms.reverse()

    # Return result
    if srcsegms_found:
        return srcsegms, trgcuts
    else:
        return [], []


def extract_categ_words_of_segm(word_array, left, right):
    # Initialize variables
    categ_words = []

    # Explore word array
    for i in range(left, right + 1):
        if is_categ(word_array[i]) or is_categ(categorize_word(word_array[i])):
            categ_words.append((i, word_array[i]))

    # Return result
    return categ_words


def decategorize(sline, tline, iline):
    src_word_array = sline.split()
    trg_word_array = tline.split()
    hyp_word_array = iline.split()

    # Extract alignment information
    srcsegms, trgcuts = extract_alig_info(hyp_word_array)

    # Iterate over target words
    output = ""
    for trgpos in range(len(trg_word_array)):

        if is_categ(trg_word_array[trgpos]):
            output += decategorize_word(trgpos, src_word_array, trg_word_array, srcsegms, trgcuts)
        else:
            output += trg_word_array[trgpos]

        if trgpos < len(trg_word_array) - 1:
            output += " "

    return output


def decategorize_word(trgpos, src_word_array, trg_word_array, srcsegms, trgcuts):
    # Check if there is alignment information available
    if len(srcsegms) == 0 or len(trgcuts) == 0:
        return trg_word_array[i]
    else:
        # Scan target cuts
        for k in range(len(trgcuts)):
            if k == 0:
                if trgpos + 1 <= trgcuts[k]:
                    trgleft = 0
                    trgright = trgcuts[k] - 1
                    break
            else:
                if trgpos + 1 > trgcuts[k - 1] and trgpos + 1 <= trgcuts[k]:
                    trgleft = trgcuts[k - 1]
                    trgright = trgcuts[k] - 1
                    break
        # Check if trgpos'th word was assigned to one cut
        if k < len(trgcuts):
            # Obtain source segment limits
            srcleft = srcsegms[k][0] - 1
            srcright = srcsegms[k][1] - 1
            # Obtain categorized words with their indices
            src_categ_words = extract_categ_words_of_segm(src_word_array, srcleft, srcright)
            trg_categ_words = extract_categ_words_of_segm(trg_word_array, trgleft, trgright)

            # Obtain decategorized word
            decateg_word = ""
            curr_categ_word = trg_word_array[trgpos]
            curr_categ_word_order = 0
            for l in range(len(trg_categ_words)):
                if trg_categ_words[l][0] == trgpos:
                    break
                else:
                    if trg_categ_words[l][1] == curr_categ_word:
                        curr_categ_word_order += 1

            aux_order = 0
            for l in range(len(src_categ_words)):
                if categorize_word(src_categ_words[l][1]) == curr_categ_word:
                    if aux_order == curr_categ_word_order:
                        decateg_word = src_categ_words[l][1]
                        break
                    else:
                        aux_order += 1

            # Return decategorized word
            if decateg_word == "":
                return trg_word_array[trgpos]
            else:
                return decateg_word
        else:
            return trg_word_array[trgpos]


class Decoder:
    def __init__(self, tmodel, lmodel, weights):
        # Initialize data members
        self.tmodel = tmodel
        self.lmodel = lmodel
        self.weights = weights

        # Checking on weight list
        if len(self.weights) != 4:
            self.weights = [1, 1, 1, 1]
        else:
            print >> sys.stderr, "Decoder weights:",
            for i in range(len(weights)):
                print >> sys.stderr, weights[i],
            print >> sys.stderr, ""

        # Set indices for weight list
        self.tmw_idx = 0
        self.phrpenw_idx = 1
        self.wpenw_idx = 2
        self.lmw_idx = 3

    def opt_contains_src_words(self, src_words, opt):

        st = ""
        src_words_array = src_words.split()
        for i in range(len(src_words_array)):
            st = st + src_words_array[i]

        if st == opt:
            return True
        else:
            return False

    def tm_ext_lp(self, new_src_words, opt, verbose):

        lp = math.log(self.tmodel.obtain_trgsrc_prob_smoothed(new_src_words, opt))

        if verbose == True:
            print >> sys.stderr, "  tm: logprob(", opt.encode("utf-8"), "|", new_src_words.encode("utf-8"), ")=", lp

        return lp

    def pp_ext_lp(self, verbose):

        lp = math.log(1.0 / math.e)

        if verbose == True:
            print >> sys.stderr, "  pp:", lp

        return lp

    def wp_ext_lp(self, words, verbose):

        nw = len(words.split())

        lp = nw * math.log(1 / math.e)

        if verbose == True:
            print >> sys.stderr, "  wp:", lp

        return lp

    def lm_transform_word(self, word):
        # Do not alter word
        return word

    def lm_transform_word_unk(self, word):
        # Introduce unknown word
        if self.lmodel.obtain_ng_count(word) == 0:
            return _global_unk_word_str
        else:
            return word

    def lm_ext_lp(self, hyp_words, opt, verbose):
        ## Obtain lm history
        rawhist = self.lmodel.get_lm_state(hyp_words)
        rawhist_array = rawhist.split()
        hist = ""
        for i in range(len(rawhist_array)):
            word = self.lm_transform_word(rawhist_array[i])
            if hist == "":
                hist = word
            else:
                hist = hist + " " + word

        # Obtain logprob for new words
        lp = 0
        opt_words_array = opt.split()
        for i in range(len(opt_words_array)):
            word = self.lm_transform_word(opt_words_array[i])
            if hist == "":
                ngram = word
            else:
                ngram = hist + " " + word
            lp_ng = math.log(self.lmodel.obtain_trgsrc_interp_prob(ngram))
            lp = lp + lp_ng
            if verbose == True:
                print >> sys.stderr, "  lm: logprob(", word.encode("utf-8"), "|", hist.encode("utf-8"), ")=", lp_ng

            hist = self.lmodel.remove_oldest_word(ngram)

        return lp

    def expand(self, tok_array, hyp, new_hyp_cov, verbose):
        # Init result
        exp_list = []

        # Obtain words to be translated
        new_src_words = ""
        last_cov_pos = self.last_cov_pos(hyp.data.coverage)
        for i in range(last_cov_pos + 1, new_hyp_cov + 1):
            if new_src_words == "":
                new_src_words = tok_array[i]
            else:
                new_src_words = new_src_words + " " + tok_array[i]

        # Obtain translation options
        opt_list = self.tmodel.obtain_opts_for_src(new_src_words)

        # If there are no options and only one source word is being covered,
        # artificially add one
        if len(opt_list) == 0 and len(new_src_words.split()) == 1:
            opt_list.append(new_src_words)

        # Print information about expansion if in verbose mode
        if verbose == True:
            print >> sys.stderr, "++ expanding -> new_hyp_cov:", new_hyp_cov, "; new_src_words:", new_src_words.encode(
                "utf-8"), "; num options:", len(opt_list)

        # Iterate over options
        for opt in opt_list:

            if verbose == True:
                print >> sys.stderr, "   option:", opt.encode("utf-8")

            # Extend hypothesis

            ## Obtain new hypothesis
            bfsd_newhyp = BfsHypdata()

            # Obtain coverage for new hyp
            bfsd_newhyp.coverage = hyp.data.coverage[:]
            bfsd_newhyp.coverage.append(new_hyp_cov)

            # Obtain list of words for new hyp
            if hyp.data.words == "":
                bfsd_newhyp.words = opt
            else:
                bfsd_newhyp.words = hyp.data.words
                bfsd_newhyp.words = bfsd_newhyp.words + " " + opt

            ## Obtain score for new hyp

            # Add translation model contribution
            tm_lp = self.tm_ext_lp(new_src_words, opt, verbose)
            w_tm_lp = self.weights[self.tmw_idx] * tm_lp

            # Add phrase penalty contribution
            pp_lp = self.pp_ext_lp(verbose)
            w_pp_lp = self.weights[self.phrpenw_idx] * pp_lp

            # Add word penalty contribution
            wp_lp = self.wp_ext_lp(opt, verbose)
            w_wp_lp = self.weights[self.wpenw_idx] * wp_lp

            # Add language model contribution
            lm_lp = self.lm_ext_lp(hyp.data.words, opt, verbose)
            w_lm_lp = self.weights[self.lmw_idx] * lm_lp

            # Add language model contribution for <bos> if hyp is
            # complete
            w_lm_end_lp = 0
            if self.cov_is_complete(bfsd_newhyp.coverage, tok_array):
                lm_end_lp = self.lm_ext_lp(bfsd_newhyp.words, _global_eos_str, verbose)
                w_lm_end_lp = self.weights[self.lmw_idx] * lm_end_lp

            if verbose == True:
                print >> sys.stderr, "   expansion ->", "w. lp:", hyp.score + w_tm_lp + w_pp_lp + w_lm_lp + \
                                                                  w_lm_end_lp, "; w. tm logprob:", w_tm_lp, \
                    "; w. pp logprob:", w_pp_lp, "; w. wp logprob:", w_wp_lp, "; w. lm logprob:", w_lm_lp, \
                    "; w. lm end logprob:", w_lm_end_lp, ";", str(
                    bfsd_newhyp)
                print >> sys.stderr, "   ----"

            # Obtain new hypothesis
            newhyp = Hypothesis()
            newhyp.score = hyp.score + w_tm_lp + w_pp_lp + w_wp_lp + w_lm_lp + w_lm_end_lp
            newhyp.data = bfsd_newhyp

            # Add expansion to list
            exp_list.append(newhyp)

        # Return result
        return exp_list

    def last_cov_pos(self, coverage):

        if len(coverage) == 0:
            return -1
        else:
            return coverage[len(coverage) - 1]

    def hyp_is_complete(self, hyp, src_word_array):

        return self.cov_is_complete(hyp.data.coverage, src_word_array)

    def cov_is_complete(self, coverage, src_word_array):

        if self.last_cov_pos(coverage) == len(src_word_array) - 1:
            return True
        else:
            return False

    def obtain_nblist(self, src_word_array, nblsize, verbose):
        # Insert initial hypothesis in stack
        priority_queue = PriorityQueue()
        hyp = Hypothesis()
        priority_queue.put(hyp)

        # Create state dictionary
        stdict = StateInfoDict()
        stdict.insert(obtain_state_info(self.tmodel, self.lmodel, hyp), hyp.score)
        stdict.insert(obtain_state_info(self.tmodel, self.lmodel, hyp), hyp.score)

        # Obtain n-best hypotheses
        nblist = []
        for i in xrange(nblsize):
            hyp = self.best_first_search(src_word_array, priority_queue, stdict, verbose)

            # Append hypothesis to nblist
            if len(hyp.data.coverage) > 0:
                nblist.append(hyp)

        # return result
        return nblist

    def obtain_detok_sent(self, tok_array, best_hyp):

        # Check if tok_array is not empty
        if len(tok_array) > 0:
            # Init variables
            result = ""
            coverage = best_hyp.data.coverage
            # Iterate over hypothesis coverage array
            for i in range(len(coverage)):
                # Obtain leftmost source position
                if i == 0:
                    leftmost_src_pos = 0
                else:
                    leftmost_src_pos = coverage[i - 1] + 1

                # Obtain detokenized word
                detok_word = ""
                for j in range(leftmost_src_pos, coverage[i] + 1):
                    detok_word = detok_word + tok_array[j]

                # Incorporate detokenized word to detokenized sentence
                if i == 0:
                    result = detok_word
                else:
                    result = result + " " + detok_word
            # Return detokenized sentence
            return result
        else:
            return ""

    def get_hypothesis_to_expand(self, priority_queue, stdict):

        while True:
            if priority_queue.empty() == True:
                return True, Hypothesis()
            else:
                hyp = priority_queue.get()
                sti = obtain_state_info(self.tmodel, self.lmodel, hyp)
                if stdict.hyp_recombined(sti, hyp.score) == False:
                    return False, hyp

    def best_first_search(self, src_word_array, priority_queue, stdict, verbose):
        # Initialize variables
        end = False
        niter = 0

        if verbose == True:
            print >> sys.stderr, "*** Starting best first search..."

        # Start best-first search
        while not end:
            # Obtain hypothesis to expand
            empty, hyp = self.get_hypothesis_to_expand(priority_queue, stdict)
            # Check if priority queue is empty
            if empty:
                end = True
            else:
                # Expand hypothesis
                if verbose == True:
                    print >> sys.stderr, "** niter:", niter, " ; lp:", hyp.score, ";", str(hyp.data)
                # Stop if the hypothesis is complete
                if self.hyp_is_complete(hyp, src_word_array) == True:
                    end = True
                else:
                    # Expand hypothesis
                    for l in range(0, _global_a_par):
                        new_hyp_cov = self.last_cov_pos(hyp.data.coverage) + 1 + l
                        if new_hyp_cov < len(src_word_array):
                            # Obtain expansion
                            exp_list = self.expand(src_word_array, hyp, new_hyp_cov, verbose)
                            # Insert new hypotheses
                            for k in range(len(exp_list)):
                                # Insert hypothesis
                                priority_queue.put(exp_list[k])
                                # Update state info dictionary
                                sti = obtain_state_info(self.tmodel, self.lmodel, exp_list[k])
                                stdict.insert(sti, exp_list[k].score)

            niter = niter + 1

            if niter > _global_maxniters:
                end = True

        # Return result
        if niter > _global_maxniters:
            if verbose == True:
                print  >> sys.stderr, "Warning: maximum number of iterations exceeded"
            return Hypothesis()
        else:
            if self.hyp_is_complete(hyp, src_word_array) == True:
                if verbose == True:
                    print >> sys.stderr, "*** Best first search finished successfully after", niter, "iterations, " \
                                                                                                     "hyp. score:", \
                        hyp.score
                hyp.score = hyp.score
                return hyp
            else:
                if verbose == True:
                    print >> sys.stderr, "Warning: priority queue empty, search was unable to reach a complete " \
                                         "hypothesis"
                return Hypothesis()

    def detokenize(self, file, verbose):
        # read raw file line by line
        lineno = 0
        for line in file:
            # Obtain array with tokenized words
            lineno = lineno + 1
            line = line.strip("\n")
            tok_array = line.split()
            nblsize = 1
            if verbose == True:
                print >> sys.stderr, ""
                print >> sys.stderr, "**** Processing sentence: ", line.encode("utf-8")

            if len(tok_array) > 0:
                # Transform array of tokenized words
                trans_tok_array = []
                for i in range(len(tok_array)):
                    trans_tok_array.append(transform_word(tok_array[i]))

                # Obtain n-best list of detokenized sentences
                nblist = self.obtain_nblist(trans_tok_array, nblsize, verbose)

                # Print detokenized sentence
                if len(nblist) == 0:
                    print line.encode("utf-8")
                    print >> sys.stderr, "Warning: no detokenizations were found for sentence in line", lineno
                else:
                    best_hyp = nblist[0]
                    detok_sent = self.obtain_detok_sent(tok_array, best_hyp)
                    print detok_sent.encode("utf-8")
            else:
                print ""

    def recase(self, file, verbose):
        # read raw file line by line
        lineno = 0
        for line in file:
            # Obtain array with tokenized words
            lineno = lineno + 1
            line = line.strip("\n")
            lc_word_array = line.split()
            nblsize = 1
            if verbose == True:
                print >> sys.stderr, ""
                print >> sys.stderr, "**** Processing sentence: ", line.encode("utf-8")

            if len(lc_word_array) > 0:
                # Obtain n-best list of detokenized sentences
                nblist = self.obtain_nblist(lc_word_array, nblsize, verbose)

                # Print recased sentence
                if len(nblist) == 0:
                    print line.encode("utf-8")
                    print >> sys.stderr, "Warning: no recased sentences were found for sentence in line", lineno
                else:
                    best_hyp = nblist[0]
                    print best_hyp.data.words.encode("utf-8")
            else:
                print ""


class Tokenizer:
    def __init__(self):
        self.RX = re.compile(r'(\w+)|([^\w\s]+)', re.U)

    def tokenize(self, s):
        aux = filter(None, self.RX.split(s))
        return filter(None, [s.strip() for s in aux])


def tokenize(string):
    tokenizer = Tokenizer()
    skel = list(annotated_string_to_xml_skeleton(string))
    for idx, (is_tag, txt) in enumerate(skel):
        if is_tag:
            skel[idx][1] = [skel[idx][1]]
        else:
            skel[idx][1] = tokenizer.tokenize(txt)
    return xml_skeleton_to_tokens(skel)


def xml_skeleton_to_tokens(skeleton):
    """
    Joins back the elements in a skeleton to return a list of tokens
    """
    annotated = []
    for _, tokens in skeleton:
        annotated.extend(tokens)
    return annotated


def lowercase(string):
    # return str.lower()
    skel = []
    for is_tag, txt in annotated_string_to_xml_skeleton(string):
        skel.append(
            (is_tag, txt.strip() if is_tag else txt.lower().strip())
        )

    return xml_skeleton_to_string(skel)


def xml_skeleton_to_string(skeleton):
    """
    Joins back the elements in a skeleton to return an annotated string
    """
    return u" ".join(txt for _, txt in skeleton)


def annotated_string_to_xml_skeleton(annotated):
    """
    Parses a string looking for XML annotations
    returns a vector where each element is a pair (is_tag, text)
    """
    offset = 0
    for m in _annotation.finditer(annotated):
        if offset < m.start():
            yield [False, annotated[offset:m.start()]]
        offset = m.end()
        g = m.groups()
        dic_g = filter(None, g[0:8])
        len_g = filter(None, g[8:11])
        if dic_g:
            yield [True, dic_g[0]]
            yield [True, dic_g[1]]
            yield [False, dic_g[2]]
            yield [True, dic_g[3]]
            yield [True, dic_g[4]]
            yield [False, dic_g[5]]
            yield [True, dic_g[6]]
            yield [True, dic_g[7]]
        elif len_g:
            yield [True, dic_g[0]]
            yield [False, dic_g[1]]
            yield [True, dic_g[2]]
        else:
            sys.stderr.write('WARNING:\n - s: %s\n - g: %s\n' % (annotated, g))
    if offset < len(annotated):
        yield [False, annotated[offset:]]


def remove_xml_annotations(annotated):
    xml_tags = {'<' + src_ann + '>', '</' + len_ann + '>', '</' + grp_ann + '>'}
    skeleton = list(annotated_string_to_xml_skeleton(annotated))
    tokens = []
    for i, is_tag, text in enumerate(skeleton):
        token = text.strip()
        if not is_tag and token:
            if i == 0:
                tokens.append(token)
            else:
                ant_is_tag, ant_text = skeleton[i - 1]
                if not ant_is_tag or (ant_is_tag and
                                              ant_text.strip() in xml_tags):
                    tokens.append(token)
    return u' '.join(tokens)
