#!/usr/bin/python

##
# \file reconstructStaticVolume.py
# \brief      Script to reconstruct an isotropic, high-resolution volume from
#             multiple stacks of low-resolution 2D slices without 
#             motion-correction.
#
# Example data can be downloaded from
# https://www.dropbox.com/sh/je6luff8y8d692e/AABx798T_PyaIXXsh0pq7rVca?dl=0 
#
# or within the shell by running 
# `curl -L https://www.dropbox.com/sh/je6luff8y8d692e/AABx798T_PyaIXXsh0pq7rVca?dl=1 > fetal_brain.zip`
#
# A volumetric reconstruction (without motion correction) can be obtained by
# running
# 
# `python reconstructStaticVolume.py --dir_input=fetal_brain --dir_output=results
# --target_stack_index=1`
#
# Example usage (tested with Python 2.7):
#       - `python reconstructStaticVolume.py --help`
#       - `python reconstructStaticVolume.py --dir_input=path-to-data`
# \author     Michael Ebner (michael.ebner.14@ucl.ac.uk)
# \date       May 2017
#

## Import libraries 
import SimpleITK as sitk
import argparse
import numpy as np
import sys
import os

## Import modules
sys.path.insert(1, os.path.abspath(\
    os.path.join(os.environ['VOLUMETRIC_RECONSTRUCTION_DIR'], 'src', 'py')))
import utilities.SimpleITKHelper as sitkh
import utilities.PythonHelper as ph
import preprocessing.DataPreprocessing as dp
import base.Stack as st
import registration.SegmentationPropagation as segprop
import reconstruction.solver.TikhonovSolver as tk


##
# Gets the parsed input line.
# \date       2017-05-18 20:09:23+0100
#
# \param      dir_output          The dir output
# \param      prefix_output       The prefix output
# \param      suffix_mask         The suffix mask
# \param      target_stack_index  The target stack index
# \param      regularization      The regularization
# \param      minimizer           The minimizer
# \param      alpha               The alpha
# \param      iter_max            The iterator maximum
# \param      verbose             The verbose
#
# \return     The parsed input line.
#
def get_parsed_input_line(
    dir_output,
    prefix_output,
    suffix_mask,
    target_stack_index, 
    regularization, 
    alpha,
    iter_max,
    verbose,
    provide_comparison,
    ):

    parser = argparse.ArgumentParser(description=
        "Volumetric MRI reconstruction framework to reconstruct an isotropic, high-resolution 3D volume from multiple stacks of 2D slices. The resolution of the computed Super-Resolution Reconstruction (SRR) is given by the in-plane spacing of the selected target stack. "
        "A region of interest can be specified by providing a mask for the selected target stack. Only this region will then be reconstructed by the SRR algorithm which can substantially reduce the computational time.",
        prog="python reconstructStaticVolume.py",
        epilog="Author: Michael Ebner (michael.ebner.14@ucl.ac.uk)",
        )

    parser.add_argument('--dir_input', type=str, help="Input directory with NIfTI files (.nii or .nii.gz).", required=True)
    parser.add_argument('--dir_output', type=str, help="Output directory. [default: %s]" %(dir_output), default=dir_output)
    parser.add_argument('--suffix_mask', type=str, help="Suffix used to associate a mask with an image. E.g. suffix_mask='_mask' means an existing image_i_mask.nii.gz represents the mask to image_i.nii.gz for all images image_i in the input directory. [default: %s]" %(suffix_mask), default=suffix_mask)
    parser.add_argument('--prefix_output', type=str, help="Prefix for SRR output file name. [default: %s]" %(prefix_output), default=prefix_output)
    parser.add_argument('--target_stack_index', type=int, help="Index of stack (image) in input directory (alphabetical order) which defines physical space for SRR. First index is 0. [default: %s]" %(target_stack_index), default=target_stack_index)
    parser.add_argument('--alpha', type=float, help="Regularization parameter alpha to solve the SR reconstruction problem:  SRR = argmin_x [0.5 * sum_k ||y_k - A_k x||^2 + alpha * R(x)]. [default: %g]" %(alpha), default=alpha)
    parser.add_argument('--regularization', type=str, help="Type of regularization for SR algorithm. Either 'TK0' or 'TK1' for zeroth or first order Tikhonov regularization, respectively. I.e. R(x) = ||x||^2 for 'TK0' or R(x) = ||Dx||^2 for 'TK1'. [default: %s]" %(regularization), default=regularization)
    parser.add_argument('--iter_max', type=int, help="Number of maximum iterations for the numerical solver. [default: %s]" %(iter_max), default=iter_max)
    parser.add_argument('--verbose', type=bool, help="Turn on/off verbose output. [default: %s]" %(verbose), default=verbose)
    parser.add_argument('--provide_comparison', type=bool, help="Turn on/off functionality to create files allowing for a visual comparison between original data and the obtained SRR. A folder 'comparison' will be created in the output directory containing the obtained SRR along with the linearly resampled original data. An additional script 'show_comparison.py' will be provided whose execution will open all images in ITK-Snap (http://www.itksnap.org/). [default: %s]" %(provide_comparison), default=provide_comparison)

    args = parser.parse_args()

    if args.verbose:
        ph.print_title("Given Input")
        print("Chosen Parameters:")
        for arg in sorted(vars(args)):
            ph.print_debug_info("%s: " %(arg), newline=False)
            print(getattr(args, arg))

    return args


"""
Main Function
"""
if __name__ == '__main__':

    time_start = ph.start_timing()

    ##-------------------------------------------------------------------------
    ## Read input
    args = get_parsed_input_line(
        dir_output="./",
        prefix_output="SRR_",
        suffix_mask="_mask",
        target_stack_index=0,
        regularization="TK1",
        alpha=0.02,
        iter_max=10,
        verbose=1,
        provide_comparison=0,
        )

    ##-------------------------------------------------------------------------
    ## Data Preprocessing
    ph.print_title("Data Preprocessing")
    segmentation_propagator = segprop.SegmentationPropagation(
        dilation_radius=3,
        dilation_kernel="Ball",
        )

    data_preprocessing = dp.DataPreprocessing.from_directory(
        dir_input=args.dir_input, 
        suffix_mask=args.suffix_mask,
        segmentation_propagator=segmentation_propagator,
        use_cropping_to_mask=True,
        target_stack_index=args.target_stack_index,
        boundary_i=0,
        boundary_j=0,
        boundary_k=0,
        unit="mm",
        )
    data_preprocessing.run_preprocessing()
    time_data_preprocessing = data_preprocessing.get_computational_time()
    stacks = data_preprocessing.get_preprocessed_stacks()

    # sitkh.show_stacks(stacks)

    ##-------------------------------------------------------------------------
    ## Super-Resolution Reconstruction (SRR)
    ph.print_title("Super-Resolution Reconstruction")
    
    ##
    # Initial, isotropic volume to define the physical space for the HR SRR
    # reconstruction. In-plane spacing of chosen template stack defines
    # the isotropic voxel size.
    HR_volume_init = stacks[0].get_isotropically_resampled_stack()
    HR_volume_init.set_filename("HR_volume_0")

    ## SRR step
    HR_volume = st.Stack.from_stack(HR_volume_init, filename="HR_volume")
    SRR = tk.TikhonovSolver(
        stacks=stacks,
        HR_volume=HR_volume,
        reg_type=args.regularization,
        minimizer="lsmr",
        iter_max=args.iter_max,
        alpha=args.alpha,
        )
    SRR.run_reconstruction()
    SRR.print_statistics()
    
    time_SRR = SRR.get_computational_time()
    elapsed_time = ph.stop_timing(time_start)

    ## Update filename
    filename = SRR.get_setting_specific_filename(prefix=args.prefix_output)
    HR_volume.set_filename(filename) 
    # HR_volume.show()
    
    ##-------------------------------------------------------------------------
    ## Write SRR to output
    HR_volume.write(directory=args.dir_output)

    ## Show SRR together with linearly resampled input data.
    ## Additionally, a script is generated to open files
    if args.provide_comparison:
        stacks_visualization = []
        stacks_visualization.append(HR_volume)
        for i in range(0, len(stacks)):
            stacks_visualization.append(stacks[i])
    
        sitkh.show_stacks(stacks_visualization, 
            show_comparison_file=args.provide_comparison,
            dir_output=os.path.join(args.dir_output, "comparison"),
            )

    ##-------------------------------------------------------------------------
    ## Summary
    ph.print_title("Summary")
    print("Computational Time for Data Preprocessing: %s" %(time_data_preprocessing))
    print("Computational Time for Super-Resolution Algorithm: %s" %(time_SRR))
    print("Computational Time for Entire Reconstruction Pipeline: %s" %(elapsed_time))